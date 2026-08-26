# PPC Lab development guide

PPC Lab should remain low-maintenance infrastructure. Changes are driven by real PowerPC research targets and must preserve deterministic behavior.

## Build modes

Release:

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
```

Sanitizers with Clang/GCC-family compilers:

```bash
cmake -S . -B build/sanitize \
  -DCMAKE_BUILD_TYPE=Debug \
  -DPPC_LAB_ENABLE_UNICORN=OFF \
  -DPPC_LAB_ENABLE_SANITIZERS=ON
cmake --build build/sanitize --parallel
ctest --test-dir build/sanitize --output-on-failure
```

One-command verification on macOS/Linux:

```bash
./Tools/verify.command
```

## CI contract

A patch should keep these green:

1. configure/build on supported CI hosts;
2. C++ harness tests;
3. call-harness tests;
4. CLI built-in selftest;
5. Python result-tool tests when Python is available;
6. GPL/SPDX and target-neutral repository invariants;
7. sanitizers where enabled by the local verification script.

Target profiles that require proprietary external bytes must not make public CI depend on those bytes.

## Adding a PPC instruction

When a real target stops on an unsupported instruction:

1. identify the exact instruction and architecture semantics from an appropriate PowerPC reference;
2. add the implementation to the built-in backend;
3. add a small synthetic test with known register/memory/CR effects;
4. test branch/link/overflow/record forms when relevant;
5. run `./Tools/verify.command`;
6. retry the real target and preserve the new target validation if it changes the reachable path.

Avoid implementing broad opcode families speculatively when the active target only requires a narrow subset.

## Adding an import stub

A reusable stub belongs in the core when the **behavior** is target-neutral. Its address never belongs in the core.

Process:

1. identify ABI inputs and outputs;
2. implement the generic behavior;
3. add it to `ImportStubKind` parsing/dispatch;
4. add a synthetic test;
5. document numerical/behavioral limitations;
6. bind the target's address in its profile script with `--stub KIND@ADDRESS`.

Historical math-library routines may differ bit-for-bit from host `libm`. Do not claim exactness unless validated.

## Adding a backend

A backend implements the `ExecutionBackend` contract and must produce PPC Lab stop reasons/state in a way that the call harness can consume consistently.

A new backend must not bypass deterministic memory/call setup merely because the underlying engine has its own convenience APIs.

## Target leakage rule

Generic directories must not contain target-specific routine addresses, target names, commercial binary data, or assumptions about one application's memory layout.

Generic areas include:

```text
include/
src/
tools/
scripts/   # except scripts explicitly operating on generic result formats
cmake/
tests/      # synthetic fixtures only
```

Target-specific material belongs under `profiles/<target>/`.

## Coding expectations

- C++20;
- explicit fixed-width integer types for emulated architectural state;
- big-endian target memory semantics must be obvious and tested;
- deterministic behavior over convenience;
- fail loudly on unsupported/unknown behavior rather than guessing;
- no mandatory heavyweight dependency for the built-in path;
- source files carry `SPDX-License-Identifier: GPL-3.0-only`.

## Release checklist

For a small release:

```bash
./Tools/verify.command
git status --short
git diff --check
```

Then verify:

- version in `CMakeLists.txt`;
- `CHANGELOG.md` entry;
- README/docs match current CLI;
- no proprietary target binaries were added;
- no target-specific addresses leaked into the core;
- GPL/SPDX markings remain correct.

PPC Lab does not need ceremonial releases for every research patch. Tag releases when a stable capability boundary is worth preserving.


## Repository invariant test

`python3 scripts/check_repository_invariants.py` is deliberately dependency-free and is also registered with CTest. It verifies that the canonical GPLv3 license is present, source/build/script entry points carry the `GPL-3.0-only` SPDX identifier, and known ReBirth/X0X regression identifiers have not leaked back into generic core/tooling directories.
