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

## Before submitting

Run:

```bash
./Tools/verify.command
git diff --check
```

For source changes, add or update a regression test. For a target-specific discovery, update that target's profile documentation/validation where appropriate.

See `docs/DEVELOPMENT.md` for implementation rules and `docs/ADDING_A_TARGET.md` for profile rules.
