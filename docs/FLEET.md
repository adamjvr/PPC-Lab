# Distributed worker fleets

PPC Lab v1.3 adds `ppc-lab-fleet`, a dependency-free scheduler above the stable `ppc-lab-job-v1` / `ppc-lab-worker-response-v1` boundary. It is intended for the case that one server is no longer enough but a permanent queue/database/web-service stack would be needless maintenance.

The fleet layer uses either local worker processes or ordinary OpenSSH endpoints. PPC Lab does not implement authentication, encryption, account management, or a network daemon; SSH remains responsible for those deployment concerns.

## Fast path

Install the same PPC Lab release on every worker host, make sure key-based SSH works noninteractively, and give each worker an absolute scratch root.

```json
{
  "schema": "ppc-lab-fleet-v1",
  "timeout": 60,
  "retries": 1,
  "hosts": [
    {
      "name": "ppc-a",
      "transport": "ssh",
      "endpoint": "research@ppc-a",
      "slots": 8,
      "root": "/srv/ppc-lab",
      "tags": ["linux", "cpu"]
    },
    {
      "name": "ppc-b",
      "transport": "ssh",
      "endpoint": "research@ppc-b",
      "slots": 8,
      "root": "/srv/ppc-lab",
      "tags": ["linux", "cpu"]
    }
  ],
  "jobs": [
    {
      "name": "constructor-a",
      "requires_tags": ["cpu"],
      "job": {
        "schema": "ppc-lab-job-v1",
        "id": "constructor-a",
        "image": {"path": "targets/app.pef", "kind": "auto"},
        "execution": {"backend": "builtin", "entry_symbol": "Probe"}
      }
    }
  ]
}
```

Run it from the machine that owns the source binaries and result directory:

```bash
ppc-lab-fleet fleet.json \
  --local-root /srv/research \
  --out /srv/results/run-001 \
  --cache /srv/cache/ppc-lab
```

`--local-root` is strongly recommended for server use. PPC Lab verifies that source image/data files are inside this tree **before hashing or staging them**.

## Host contract

Every host has:

- a unique `name`;
- `transport`: `ssh` or `local`;
- `slots`: the maximum number of concurrent PPC Lab jobs assigned there;
- `root`: the worker's scratch/containment root;
- optional `tags` used by jobs for eligibility;
- optional `ppc_lab`, `worker`, and `python` command/path overrides.

An SSH host additionally has `endpoint`, in normal OpenSSH form such as `research@host.example`.

For SSH transport, `root` must be an **absolute POSIX path**. The default commands are `ppc-lab`, `ppc-lab-worker`, and `python3`, so a normal `cmake --install` deployment whose `bin` directory is on `PATH` needs no command overrides.

Local hosts are primarily useful for development, CI, or deliberately partitioning one large machine. Relative local roots are resolved against the fleet manifest directory.

## Capability negotiation

Before scheduling anything, the fleet controller runs:

```bash
ppc-lab capabilities --json
```

on every host. A host is healthy only when it advertises:

- `ppc-lab-capabilities-v1`;
- `ppc-lab-job-v1`;
- `ppc-lab-worker-response-v1`;
- an available worker command.

All participating hosts must run the same PPC Lab engine version. Hosts with a different version are excluded rather than mixing execution semantics inside one result set.

A job requesting `execution.backend=unicorn` only lands on a host advertising Unicorn. `builtin` jobs may run on every compatible PPC Lab host. Jobs may also specify `requires_tags` outside the stable job object to restrict placement without contaminating `ppc-lab-job-v1`.

## Content-addressed staging

The controller resolves and SHA-256 hashes each source image/data file. A worker receives the content under:

```text
<host root>/.ppc-lab/store/<sha256>
```

The job sent to that worker is a copy whose image paths point at the staged objects; the original job JSON remains the cache/research identity.

Local staging uses an atomic copy/rename. SSH staging:

1. asks remote Python whether the content-addressed object already exists and hashes correctly;
2. uploads only when required using `scp`;
3. verifies the uploaded bytes remotely with SHA-256;
4. atomically moves the verified temporary object into the store.

Because the filename is the content hash, repeated jobs and later runs naturally reuse target binaries without a separate artifact service.

PPC Lab intentionally does not delete the remote content store automatically. It is safe to prune when no jobs are running; missing objects will simply be staged again.

## Scheduling and slots

The controller uses a bounded thread pool and one semaphore per host. `slots` therefore remains a hard local controller limit even when many jobs are queued.

Initial placement rotates deterministically by job index so equally eligible hosts receive work rather than all jobs preferring the first host. Tags/backend rules are applied before scheduling.

This is not a cluster fairness scheduler. It is deliberately a small research-fleet controller for machines you own/control.

## Retry/failover behavior

`retries` controls additional attempts after the first one. Retries are used only for conditions that may improve on another host:

- staging/SSH transport failure;
- invalid/missing worker transport response;
- transport timeout;
- a worker response explicitly marked `timed_out`.

Normal PPC execution failures are **not** retried merely because another host exists. A deterministic guest stop, unsupported opcode, bad binding, or other research result should remain visible rather than being disguised as infrastructure instability.

The result record preserves every attempt and the final host.

## Resume and central cache

Each fleet job receives a SHA-256 cache key derived from:

- `ppc-lab-fleet-v1`;
- the canonical original `ppc-lab-job-v1` document;
- the negotiated PPC Lab engine version;
- the size and SHA-256 of every source input.

A matching result already present in `--out` is resumed by default. `--no-resume` ignores result-directory reuse while still allowing `--cache` reuse.

Changing binary bytes, job configuration, or PPC Lab version changes the cache key. Paths/mtimes alone are not trusted. Only successful worker responses enter the shared cache; failed guest executions remain evidence in their run directory but are not promoted into reusable shared cache state.

Fleet cache keys are opaque implementation identities. Do not reproduce the hash algorithm in client software; persist/compare the string PPC Lab gives you.

## Result contracts

Per-job files use `ppc-lab-fleet-job-result-v1` and contain:

- cache key and engine version;
- source-input fingerprints;
- final host;
- every scheduling/staging/transport attempt;
- the complete stable `ppc-lab-worker-response-v1`.

`summary.json` uses `ppc-lab-fleet-summary-v1` and contains run counts, host health/capabilities, and one row per job.

All controller-created JSON files use temporary files plus atomic rename.

## SSH deployment

A minimal worker host needs PPC Lab installed and a writable scratch root:

```bash
cmake --install build/release --prefix "$HOME/.local"
mkdir -p /srv/ppc-lab
```

Ensure the installed `bin` directory is visible to noninteractive SSH commands. Then from the controller:

```bash
ssh -o BatchMode=yes research@ppc-a 'ppc-lab capabilities --json'
ssh -o BatchMode=yes research@ppc-a 'ppc-lab-worker --help'
```

`ppc-lab-fleet` itself defaults to `BatchMode=yes` and a finite SSH connection timeout so a fleet run does not hang on a password/host prompt. Additional OpenSSH options can be supplied with repeated `--ssh-option` values.

Alternative SSH/scp executables can be selected through `--ssh` / `--scp` or the `PPC_LAB_SSH` / `PPC_LAB_SCP` environment variables.

## Security boundary

PPC Lab fleet mode assumes the controller and worker accounts are trusted research infrastructure.

Important boundaries:

- SSH provides authentication/encryption; PPC Lab does not replace it.
- `--local-root` contains what the controller may read/hash/stage.
- each worker still enforces its own `--root` when executing the rewritten staged job;
- root containment is a path policy, **not an OS sandbox**;
- untrusted binaries or hostile collaborators should still be isolated with an OS account, container, VM, namespace/sandbox, or equivalent host controls.

Do not point a worker root at `/` merely to avoid configuring paths.

## Local-fleet CI model

The repository regression uses multiple `transport=local` hosts plus an intentionally dead host. It proves scheduling, health exclusion, per-host usage, staging, resume, cache reuse/invalidation, tags, and root containment without requiring network access in CI.

Real SSH deployments should additionally be validated in the environment that owns the actual host keys, accounts, routing, and filesystem policy; those are deployment properties rather than portable repository tests.

## Relationship to v1.2 orchestration

Use `ppc-lab-orchestrate` when one machine is enough. It is simpler and has fewer moving parts.

Use `ppc-lab-fleet` when the same stable job set needs to span multiple installed PPC Lab hosts. Fleet mode does not replace the worker protocol or require client projects to understand SSH details; jobs remain `ppc-lab-job-v1`.

## Publish completed fleet evidence

A controller can index a completed run immediately:

```bash
ppc-lab-fleet fleet.json --out /srv/results/run-001 --evidence-store /srv/ppc-evidence
```

Only PPC Lab JSON output is copied into the evidence store. The fleet's staged target objects and source binaries are not copied by evidence ingestion; their SHA-256 fingerprints remain searchable provenance. See [`EVIDENCE_STORE.md`](EVIDENCE_STORE.md).

