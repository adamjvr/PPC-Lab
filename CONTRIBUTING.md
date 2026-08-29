# Contributing to PPC Lab

PPC Lab is a GPLv3 PowerPC reverse-engineering tool intended to stay small, reusable, and useful across unrelated projects.

## License

By submitting a contribution, you agree that your contribution is licensed under the repository's **GNU General Public License version 3.0 only** (`GPL-3.0-only`).

Do not contribute code or data you do not have the right to redistribute.

## The preferred kind of contribution

The best patch usually starts with a concrete blocked research workload:

- one missing PPC instruction;
- one reusable ABI/runtime behavior;
- one generic loader/helper justified by multiple targets;
- one deterministic comparison or trace improvement;
- one bug found by an actual target/profile.

PPC Lab is deliberately not trying to become a complete emulator suite by roadmap alone.

## Proprietary target material

Do not add commercial/proprietary executables, ROMs, firmware, samples, or other target assets unless redistribution is clearly permitted.

Target profiles should normally contain only redistributable:

- addresses and symbols;
- scripts;
- hashes;
- derived metadata;
- synthetic fixtures;
- expected fingerprints;
- validation notes/results.

## Target-neutral core

Target-specific addresses and assumptions belong under `profiles/<target>/`, never in the generic execution core.

## Loader changes

Executable-loader changes need synthetic, redistributable fixtures and explicit rejection tests for unsupported formats. A loader must not silently accept a file whose relocations, ABI setup, or byte order PPC Lab does not understand.

## Before submitting

Run:

```bash
./Tools/verify.command
git diff --check
```

For source changes, add or update a regression test. For a target-specific discovery, update that target's profile documentation/validation where appropriate.

See `docs/DEVELOPMENT.md` for implementation rules and `docs/ADDING_A_TARGET.md` for profile rules.

## Server/fleet changes

Worker, orchestration, or fleet changes must preserve the stable v1 job/response boundary unless a new schema is deliberately introduced. Network-independent CI tests should simulate multiple local hosts and failures; do not make the normal repository suite depend on public network access or developer SSH credentials. Transport code must keep root-containment checks before reading/hashing/staging source inputs.

## Evidence-store changes

Evidence-store changes must remain migration-conscious and dependency-light. `ppc-lab-evidence` may index PPC Lab JSON and target-input hashes, but it must not silently copy target executables/firmware into the store. Schema/query changes need deterministic temporary-directory regressions; integrity checks must hash the actual stored bytes, and an existing store must never be mutated by a read-only query/report/verify command.

## HTTP API changes

Changes to `ppc-lab-api` must preserve `ppc-lab-job-v1` as the execution payload, retain loopback-first/default-safe binding, avoid shell command construction, and add regression coverage for authentication/request containment when the network surface changes. Do not add framework/cloud dependencies merely for convenience; the service layer is intentionally thin and optional.



## Exploration manifests

Keep guided-exploration domains deterministic and bounded. Prefer values justified by the target ABI/data model over enormous random domains. New mutation-axis families must preserve the worker/root safety boundary and arrive with a regression test. Do not commit proprietary target binaries merely to make an exploration manifest self-contained.
## Campaign-layer changes

Changes to `ppc-lab-campaign` should compose existing stable tools/protocols rather than duplicate execution, corpus, triage, or evidence semantics. New campaign policy must remain bounded, checkpointable, root-safe, and covered by a synthetic end-to-end regression. Do not make campaign convenience a reason to archive proprietary target binaries.


## Scheduler changes

`ppc-lab-schedule` is an outer resource-governance layer; it should invoke stable campaign tooling rather than duplicate campaign research logic. Scheduler changes must keep ordering deterministic, preserve exact manifest-hash resume, treat terminal admission decisions as terminal, and include synthetic regressions for fairness/quota/cancellation semantics. Do not turn scheduler policy into a reason to copy target binaries or add a mandatory queue/database service.

## Hypothesis contributions

Hypothesis-engine changes must remain deterministic and evidence-first. New role families or scoring terms need a regression that shows both supporting and contradicting evidence, must expose their scoring inputs in machine-readable output, and must not auto-promote a candidate. Follow-up experiments must use existing PPC Lab execution/exploration contracts and preserve the target-binary/root-safety boundaries.

## PPC Lab 3 maintenance boundary

PPC Lab 3.0 closes the standing feature roadmap. Please do not add speculative PPC64, little-endian, JIT, OS-runtime, service-framework, or database work without a real target/deployment that demonstrates the requirement. Persisted-format changes need an explicit migration and rollback-safe backup path through `ppc-lab-platform`.

## Target profiles and release artifacts

Use `ppc-lab-target init/validate/pack` for new target adapters. Keep private/proprietary target bytes outside public profiles unless redistribution rights are explicit. Before proposing release-engineering changes, run `tests/test_target_sdk.py` and `tests/test_release_engineering.py`; compatibility-number changes require an intentional documented contract decision.
