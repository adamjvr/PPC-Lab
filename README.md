# PPC Lab

**Deterministic PowerPC execution and reverse-engineering research platform.**

PPC Lab is a headless, reusable harness for executing isolated PowerPC routines, firmware fragments, relocated application code, and decompiler research fixtures without booting the original operating system. It grew out of a working Classic Mac / ReBirth research harness, but the execution core is target-neutral.

PPC Lab is intentionally **infrastructure, not a forever-project**: add capability when a real reverse-engineering target needs it, keep the implementation small and deterministic, add a regression test, and get back to the project that needed the research.

**License:** GNU General Public License v3.0 only (`GPL-3.0-only`). See [`LICENSE`](LICENSE).

## What works now

- dependency-free `builtin-ppc32be` interpreter;
- optional Unicorn PPC32 big-endian backend when Unicorn 2.x is available;
- deterministic code/data/import/heap/stack maps;
- direct entry-point calls;
- Classic CFM transition-vector calls (`entry`, `TOC/r2`, `r12`);
- GPR/FPR initialization and deterministic memory writes;
- import-range traps for unresolved external calls;
- target-supplied runtime stubs via `--stub KIND@ADDRESS`;
- instruction limits and trace ranges;
- memory dumps with FNV-1a64 fingerprints;
- machine-readable JSON results;
- byte and float32 differential comparison tools;
- Release tests plus optional Clang ASan/UBSan verification;
- target profiles kept outside the execution core.

The built-in interpreter already executes the original external ReBirth Distortion constructor regression used to qualify the first harness: **133,027 PPC instructions** to normal return with the known object fingerprint. That workload is preserved under `profiles/rebirth/`; no commercial bytes are included.

## Fastest start

macOS or Linux:

```bash
./Tools/verify.command
./build/release/ppc-lab selftest --backend builtin
```

Windows (PowerShell):

```powershell
cmake -S . -B build/release -DPPC_LAB_ENABLE_UNICORN=OFF
cmake --build build/release --config Release
ctest --test-dir build/release -C Release --output-on-failure
```

For the shortest useful walkthrough, read [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Build

### macOS / Linux

Full verification:

```bash
./Tools/verify.command
```

Build only:

```bash
./Tools/build.command
```

Direct CMake:

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
```

Binary:

```bash
./build/release/ppc-lab
```

### Windows

```powershell
cmake -S . -B build/release -DPPC_LAB_ENABLE_UNICORN=OFF
cmake --build build/release --config Release
ctest --test-dir build/release -C Release --output-on-failure
```

The dependency-free backend is always available. Unicorn is optional and is discovered at configure time.

## First five commands

```bash
# 1. Built-in CPU/memory/ABI self-tests
./build/release/ppc-lab selftest --backend builtin

# 2. Execute raw PPC32-BE code at an explicit entry
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --set r3=5 \
  --max-instructions 100000

# 3. Execute through a CFM transition vector
./build/release/ppc-lab call \
  --code code.bin \
  --data data.bin \
  --transition-vector 0x20005224

# 4. Bind only the runtime calls this target needs
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --stub sin@0x30000014 \
  --stub blockmove@0x300001c8

# 5. Emit deterministic result data
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --dump 0x40000000:128 \
  --json /tmp/ppc-result.json
```

Run `./build/release/ppc-lab` with no arguments for the complete built-in syntax summary. See [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) for option semantics and exit codes.

## Built-in import stubs

The core knows **behaviors**, never target addresses:

```text
pow
cos
sqrt
sin
exp
blockmove
```

A target profile binds those behaviors to addresses at runtime. Unknown imports remain traps. Host `libm` transcendental stubs are execution aids and are **not** claimed bit-exact to historical PowerPC math libraries.

## Repository layout

```text
PPC-Lab/
├── include/ppclab/ppc/   reusable C++ API
├── src/                  interpreter, memory, execution, import stubs
├── tools/                ppc-lab CLI
├── scripts/              build, verification, result/diff tooling
├── tests/                synthetic deterministic regression tests
├── profiles/             target-specific addresses/scripts/expectations
│   └── rebirth/           first real external regression workload
├── docs/                 user, architecture, development, and research docs
├── Tools/                double-clickable shell entry points
├── .github/workflows/    low-maintenance CI
├── CONTRIBUTING.md       contribution and patch rules
└── LICENSE               GNU GPL v3.0 only
```

## Documentation map

| Document | Purpose |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Get from clone to first deterministic PPC call quickly. |
| [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) | Complete current CLI, defaults, stop reasons, and exit codes. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Core/profile/backend boundaries and design invariants. |
| [`docs/ADDING_A_TARGET.md`](docs/ADDING_A_TARGET.md) | Create a target profile without contaminating the core. |
| [`docs/RESEARCH_WORKFLOW.md`](docs/RESEARCH_WORKFLOW.md) | Recommended decompilation and behavioral-research loop. |
| [`docs/RESULT_FORMAT.md`](docs/RESULT_FORMAT.md) | JSON schema and deterministic dump/fingerprint conventions. |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Build modes, tests, sanitizers, opcode/stub additions, release checklist. |
| [`docs/HISTORY.md`](docs/HISTORY.md) | Provenance of the original working harness extraction. |
| [`profiles/rebirth/README.md`](profiles/rebirth/README.md) | External ReBirth regression workload and known baseline. |

## Design rule

**No target owns PPC Lab.**

ReBirth, a Classic Mac application, a console executable, an embedded firmware image, or a future hardware project can add a profile. The CPU/memory/execution library must not acquire target-specific addresses or commercial code.

## Current scope

PPC Lab is presently a **PPC32 big-endian research harness**, strongest on C/C++ code shaped like 1990s/2000s desktop PowerPC. It is not a full Mac OS emulator, console emulator, firmware simulator, or complete PowerPC ISA implementation.

When execution stops on an unsupported instruction, that stop is deliberate: the PC/opcode becomes the next concrete implementation target only if a real project needs it.

## ReBirth regression profile

```bash
export PPC_LAB_REBIRTH_CODE=/path/ReBirth_Engine.sec0.reloc.bin
export PPC_LAB_REBIRTH_DATA=/path/ReBirth_Engine.sec1.reloc.bin
./profiles/rebirth/scripts/distortion_ctor.sh
```

See [`profiles/rebirth/README.md`](profiles/rebirth/README.md).

## License and external target bytes

PPC Lab source code, scripts, tests, and the repository's redistributable profile material are licensed under the **GNU General Public License version 3.0 only** (`GPL-3.0-only`).

PPC Lab does **not** include commercial/proprietary target executables. A binary supplied by a researcher at runtime is input data to the tool; placing or analyzing that binary with PPC Lab does not by itself make that binary part of PPC Lab or relicense it. Researchers remain responsible for having the right to possess and analyze their target material and for complying with applicable law and license terms.

See [`LICENSE`](LICENSE) for the full GPLv3 text.
