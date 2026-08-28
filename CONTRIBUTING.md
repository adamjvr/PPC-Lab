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

