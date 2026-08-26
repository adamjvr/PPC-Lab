# PPC Lab

**Deterministic PowerPC execution and reverse-engineering research platform.**

PPC Lab is a headless, reusable harness for executing isolated PowerPC routines,
firmware fragments, relocated application code, and executable images without
booting the original operating system. It grew out of a working Classic Mac /
ReBirth research harness, but the execution core is target-neutral.

PPC Lab is intentionally **infrastructure, not a forever-project**: add
capability when a real reverse-engineering target needs it, keep the
implementation small and deterministic, add a regression test, and get back to
the project that needed the research.

**License:** GNU General Public License v3.0 only (`GPL-3.0-only`). See
[`LICENSE`](LICENSE).

## What works now

- dependency-free `builtin-ppc32be` interpreter;
- optional Unicorn PPC32 big-endian backend when Unicorn 2.x is available;
- **dependency-free ELF32 big-endian PowerPC `ET_EXEC` loader**;
- automatic `PT_LOAD` mapping with permissions and BSS zero-fill;
- `elf-info` inspection and lightweight raw/ELF `disasm` commands;
- deterministic raw code/data/import/heap/stack maps;
- direct entry-point calls;
- ELF entry-point execution with explicit entry override;
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

The built-in interpreter already executes the original external ReBirth
Distortion constructor regression used to qualify the first harness: **133,027
PPC instructions** to normal return with the known object fingerprint. That
workload is preserved under `profiles/rebirth/`; no commercial bytes are
included.

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

For the shortest useful walkthrough, read
[`docs/QUICKSTART.md`](docs/QUICKSTART.md).

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

The dependency-free interpreter and ELF loader are always available. Unicorn is
optional and discovered at configure time.

## First useful commands

```bash
# CPU/memory/ABI self-tests
./build/release/ppc-lab selftest --backend builtin

# Inspect a PPC ELF without executing it
./build/release/ppc-lab elf-info firmware.elf

# Disassemble from its ELF entry point
./build/release/ppc-lab disasm --elf firmware.elf --count 32

# Execute a supported ELF32 PPC executable
./build/release/ppc-lab call \
  --elf firmware.elf \
  --backend builtin \
  --max-instructions 100000

# Execute an isolated function from the ELF image
./build/release/ppc-lab call \
  --elf firmware.elf \
  --entry 0x00104560 \
  --set r3=5

# Execute raw relocated PPC32-BE code
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --set r3=5

# Execute through a CFM transition vector
./build/release/ppc-lab call \
  --code code.bin \
  --data data.bin \
  --transition-vector 0x20005224

# Bind only the runtime calls this target needs
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --stub sin@0x30000014 \
  --stub blockmove@0x300001c8

# Emit deterministic result data
./build/release/ppc-lab call \
  --code code.bin \
  --entry 0x10000000 \
  --dump 0x40000000:128 \
  --json /tmp/ppc-result.json
```

Run `./build/release/ppc-lab` with no arguments for the built-in syntax summary.
See [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) for complete option
semantics and exit codes.

## ELF32 intake in v0.2.0

PPC Lab now directly accepts fixed-address ELF32 PowerPC executables when they
are:

```text
ELFCLASS32
ELFDATA2MSB
EM_PPC
ET_EXEC
```

`PT_LOAD` segments are mapped at their virtual addresses, file bytes are copied,
BSS tails are zero-filled, and `R/W/X` permissions are derived from ELF flags.
The file's `e_entry` is used unless an explicit entry or transition vector
overrides it.

PPC Lab deliberately rejects relocatable/shared ELF, PPC64, and little-endian
ELF until a real project justifies the corresponding relocation/architecture
work. See [`docs/ELF32.md`](docs/ELF32.md).

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

A target profile binds those behaviors to addresses at runtime. Unknown imports
remain traps. Host `libm` transcendental stubs are execution aids and are
**not** claimed bit-exact to historical PowerPC math libraries.

## Repository layout

```text
PPC-Lab/
├── include/ppclab/ppc/   reusable C++ API, including ELF32 loader
├── src/                  interpreter, memory, ELF loading, execution, stubs
├── tools/                ppc-lab CLI
├── scripts/              build, verification, result/diff tooling
├── tests/                synthetic deterministic regression tests
├── profiles/             target-specific addresses/scripts/expectations
│   └── rebirth/           first real external regression workload
├── docs/                 user, architecture, loader, development, research docs
├── Tools/                double-clickable shell entry points
├── .github/workflows/    low-maintenance CI
├── CONTRIBUTING.md       contribution and patch rules
└── LICENSE               GNU GPL v3.0 only
```

## Documentation map

| Document | Purpose |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | Clone to first deterministic PPC call quickly. |
| [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) | Current CLI, defaults, commands, stop reasons, exit codes. |
| [`docs/ELF32.md`](docs/ELF32.md) | Exact ELF32 PowerPC loader contract and limitations. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Core/loader/profile/backend boundaries and invariants. |
| [`docs/ADDING_A_TARGET.md`](docs/ADDING_A_TARGET.md) | Add a target profile without contaminating the core. |
| [`docs/RESEARCH_WORKFLOW.md`](docs/RESEARCH_WORKFLOW.md) | Recommended decompilation and behavioral-research loop. |
| [`docs/RESULT_FORMAT.md`](docs/RESULT_FORMAT.md) | JSON schema and deterministic dump/fingerprint conventions. |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Builds, tests, sanitizers, opcode/stub/loader additions, releases. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Demand-driven capability buckets; explicitly not a schedule. |
| [`docs/HISTORY.md`](docs/HISTORY.md) | Provenance of the original working harness extraction. |
| [`profiles/rebirth/README.md`](profiles/rebirth/README.md) | External ReBirth regression workload and known baseline. |

## Design rule

**No target owns PPC Lab.**

ReBirth, a Classic Mac application, an ELF firmware image, a console executable,
or a future hardware project can add a profile. CPU/memory/execution code must
not acquire target-specific addresses or commercial code.

Generic loaders are allowed when the **file format itself** is reusable across
targets. Target-specific relocation recipes and runtime assumptions remain in
profiles until repeated reuse justifies promotion.

## Current scope

PPC Lab is presently a **PPC32 big-endian research harness**. It is strongest on
C/C++ code shaped like 1990s/2000s desktop PowerPC and fixed-address PPC ELF
executables/firmware. It is not a full Mac OS emulator, Linux emulator, console
emulator, firmware simulator, dynamic linker, or complete PowerPC ISA
implementation.

When execution stops on an unsupported instruction, import, relocation, or
runtime assumption, that stop is deliberate: it becomes the next concrete
implementation target only if a real project needs it.

## ReBirth regression profile

```bash
export PPC_LAB_REBIRTH_CODE=/path/ReBirth_Engine.sec0.reloc.bin
export PPC_LAB_REBIRTH_DATA=/path/ReBirth_Engine.sec1.reloc.bin
./profiles/rebirth/scripts/distortion_ctor.sh
```

See [`profiles/rebirth/README.md`](profiles/rebirth/README.md).

## License and external target bytes

PPC Lab source code, scripts, tests, and the repository's redistributable profile
material are licensed under the **GNU General Public License version 3.0 only**
(`GPL-3.0-only`).

PPC Lab does **not** include commercial/proprietary target executables. A binary
supplied by a researcher at runtime is input data to the tool; placing or
analyzing that binary with PPC Lab does not by itself make that binary part of
PPC Lab or relicense it. Researchers remain responsible for having the right to
possess and analyze their target material and for complying with applicable law
and license terms.

See [`LICENSE`](LICENSE) for the full GPLv3 text.
