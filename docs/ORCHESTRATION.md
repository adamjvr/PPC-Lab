# Parallel server orchestration

PPC Lab v1.2 adds a dependency-free scheduler **above** the stable v1.1 worker protocol. The scheduler does not create a service, database, queue, or cluster manager. It gives a server one reliable command for running many `ppc-lab-job-v1` jobs concurrently, resuming interrupted result directories, and reusing deterministic cached results.

Installed command:

```bash
ppc-lab-orchestrate manifest.json \
  --out results/run-001 \
  --cache /srv/ppc-cache \
  --root /srv/ppc-work \
  --parallel 16
```

Source-tree use:

```bash
python3 scripts/ppc_lab_orchestrate.py manifest.json \
  --ppc-lab ./build/release/ppc-lab \
  --worker scripts/ppc_lab_worker.py \
  --out results/run-001 \
  --cache .cache/ppc-lab \
  --parallel 8
```

## Manifest contract

Schema: `ppc-lab-orchestration-v1`.

A manifest may contain inline jobs and/or references to standalone v1 job files:

```json
{
  "schema": "ppc-lab-orchestration-v1",
  "id": "constructor-sweep",
  "parallelism": 8,
  "jobs": [
    {
      "name": "inline-probe",
      "job": {
        "schema": "ppc-lab-job-v1",
        "id": "inline-probe",
        "image": {"path": "targets/app.pef", "kind": "auto"},
        "execution": {"backend": "builtin", "entry_symbol": "Probe"},
        "registers": {"r3": "0x40010000"}
      }
    },
    {"name": "render-64", "path": "jobs/render-64.json"},
    {"name": "render-128", "path": "jobs/render-128.json"}
  ]
}
```

Relative paths inside an inline job are resolved against the manifest directory. Relative paths inside a referenced job are resolved against that job file's directory. This allows a repository to keep target fixtures and job descriptions together without depending on the shell's current directory.

## Parallel execution

`--parallel N` overrides `manifest.parallelism`. If neither is supplied, PPC Lab uses up to the host CPU count, capped by the number of jobs.

The scheduler uses a bounded standard-library thread pool whose work items are worker subprocesses. PPC execution therefore remains process-contained and uses exactly the same v1 worker contract as one-shot/SSH jobs.

Individual guest failures are recorded and do not discard successful sibling jobs. The orchestrator exits `0` when every job has `response.ok=true`, `1` when one or more jobs completed with a failed PPC execution, and `2` for orchestration/manifest/setup errors.

## Deterministic cache keys

Each job receives a SHA-256 cache key derived from:

- the canonical `ppc-lab-job-v1` JSON;
- the PPC Lab engine identity/capabilities relevant to execution;
- the SHA-256 and size of every input image/data file;
- the orchestration protocol version.

The cache does **not** trust path mtimes. Replacing `target.elf` with different bytes changes the cache key even if the filename stays identical. Changing the job configuration or PPC Lab version also changes the key.

Only successful worker responses are written to the shared cache. Failed executions remain in the run result directory as evidence but are rerun next time unless explicitly resumed from that same directory.

Shared cache layout is content addressed:

```text
CACHE/
  ab/
    abcd...<64-hex-key>.json
```

Use `--no-cache-read` or `--no-cache-write` when a particular research run must bypass either side of the cache.

## Resume semantics

Use:

```bash
ppc-lab-orchestrate manifest.json --out results/run-001 --resume ...
```

A prior result is reused only if its recorded cache key exactly matches the current job, engine, and input fingerprints. Stale or malformed files are ignored and the job is executed again.

This makes an interrupted 5,000-job research sweep restartable without turning the scheduler into a persistent database project.

## Result directory

Each job writes an atomic record:

```text
0000-inline-probe.json
0001-render-64.json
0002-render-128.json
summary.json
```

A job record uses `ppc-lab-orchestration-job-result-v1` and contains the cache key, input fingerprints, engine version, duration, reuse mode (`executed`, `resume`, or `cache`), and the complete `ppc-lab-worker-response-v1`.

`summary.json` uses `ppc-lab-orchestration-summary-v1` and reports job counts, failures, parallelism, cache/resume statistics, engine capabilities, and the per-job result filenames.

Result files are written using temporary files plus atomic rename so an interrupted host does not leave a half-written JSON document that later looks valid.

## Filesystem containment

For server use, pass `--root`. The orchestrator checks image/data inputs against the root **before hashing them**, and every worker independently performs the v1.1 root-containment check again before execution.

This prevents the cache/fingerprint layer from reading arbitrary files outside the intended research tree. `--root` is still not an OS security sandbox; untrusted workloads should run under a restricted account/container/VM.

## Worker base directory

v1.2 adds `ppc-lab-worker --base-dir DIRECTORY` for stdin/NDJSON clients. It only changes how relative job paths are resolved. `--root` remains an independent containment boundary.

This was added so orchestration can submit inline JSON through stdin while retaining manifest-relative paths and a strict server root.

## Relationship to `ppc_lab_batch.py`

The older `ppc-lab-experiment-v1` batch script remains available for quick CLI-argument parameter sweeps. The v1.2 orchestrator is the preferred server-scale boundary because it operates on the stable `ppc-lab-job-v1` protocol, supports concurrency, caching, resumability, filesystem containment, and installed tooling.

Use the old batch tool when generating a small ad-hoc sweep is faster. Use orchestration when results need to be durable infrastructure.
