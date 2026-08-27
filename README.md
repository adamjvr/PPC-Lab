# PPC Lab

**Deterministic PowerPC binary intake, execution, and reverse-engineering infrastructure.**

PPC Lab is a headless GPLv3 research harness for loading PowerPC binaries,
executing isolated routines, tracing behavior, and turning original machine code
into reproducible evidence for decompilation and clean-room reconstruction. It
is deliberately project-neutral and deliberately low-maintenance: add a
capability when a real target needs it, lock that capability down with a test,
and get back to the actual reverse-engineering project.

**License:** GNU General Public License version 3 only (`GPL-3.0-only`). See
[`LICENSE`](LICENSE).

## v0.3.0 — Binary Intake Blitz

PPC Lab can now natively intake the three PowerPC formats most useful to our
current and likely future work:

- **ELF32 big-endian PowerPC** — `ET_EXEC`, `ET_DYN`, and `ET_REL`, including
  sections, symbols, rebasing, BSS, and common System V PPC relocations;
- **32-bit big-endian PowerPC Mach-O** — thin or fat containers containing
  `MH_OBJECT`, `MH_EXECUTE`, `MH_DYLIB`, or `MH_BUNDLE`, with symbols, entry
  discovery, rebasing where required, and common PPC relocations;
- **PEF/CFM PowerPC** — section instantiation, pattern-initialized data,
  imports/exports, main/init/term discovery, and standard PEF relocation
  bytecode.

Raw relocated code/data remains supported for research cases where a custom
extractor is still the right tool.

## Fast start

```bash
./Tools/verify.command
./build/release/ppc-lab selftest --backend builtin
```

Inspect any supported native image without executing it:

```bash
./build/release/ppc-lab image-info target.bin
./build/release/ppc-lab symbols target.bin
```

Disassemble or execute it:

```bash
./build/release/ppc-lab disasm --pef target.pef --count 32
./build/release/ppc-lab call --pef target.pef --backend builtin

./build/release/ppc-lab disasm --macho target.macho --count 32
./build/release/ppc-lab call --macho target.macho --backend builtin

./build/release/ppc-lab disasm --elf target.elf --count 32
./build/release/ppc-lab call --elf target.elf --backend builtin
```

For relocatable/shared images, choose a deterministic base and bind unresolved
imports explicitly:

```bash
./build/release/ppc-lab call \
  --elf object.o \
  --image-base 0x12000000 \
  --entry-symbol my_function \
  --bind malloc=0x30001000 \
  --stub blockmove@0x30002000 \
  --set r3=5 \
  --json /tmp/result.json
```

The important rule is that **addresses are target policy**. Generic PPC Lab
knows formats and reusable runtime behaviors; profiles provide target-specific
addresses, bindings, inputs, and expected results.

## Core capabilities

- dependency-free `builtin-ppc32be` interpreter;
- optional Unicorn PPC32 big-endian backend when Unicorn 2.x is available;
- deterministic memory maps and register initialization;
- direct function calls and symbol-selected entry points;
- Classic CFM transition-vector calls (`entry`, TOC/`r2`, `r12`);
- GPR/FPR setup and deterministic memory writes;
- import traps and explicit symbol bindings;
- reusable runtime stubs (`pow`, `cos`, `sqrt`, `sin`, `exp`, `blockmove`);
- instruction limits, trace output, and trace ranges;
- memory dumps with FNV-1a64 fingerprints;
- machine-readable JSON results;
- byte/float differential comparison tools;
- synthetic loader/relocation/execution regressions;
- GPL/SPDX/version/target-neutrality repository invariants;
- low-maintenance macOS/Linux/Windows CI.

The original external Classic Mac regression remains preserved as a target
profile: the ReBirth Distortion constructor has a known successful 133,027-
instruction run and object fingerprint, but no proprietary bytes are included in
PPC Lab.

## Commands

```text
ppc-lab selftest [--backend auto|builtin|unicorn]
ppc-lab image-info FILE
ppc-lab elf-info FILE
ppc-lab macho-info FILE
ppc-lab pef-info FILE
ppc-lab symbols FILE
ppc-lab disasm (--code FILE | --elf FILE | --macho FILE | --pef FILE) ...
ppc-lab call   (--code FILE | --elf FILE | --macho FILE | --pef FILE) ...
```

Run `ppc-lab` without arguments for the compact syntax summary. The complete
contract is in [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md).

## Build

### macOS / Linux

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

### Windows

```powershell
cmake -S . -B build/release -DPPC_LAB_ENABLE_UNICORN=OFF
cmake --build build/release --config Release
ctest --test-dir build/release -C Release --output-on-failure
```

The built-in interpreter and all native image loaders have no mandatory
third-party runtime dependency. Unicorn is optional.

## Repository layout

```text
PPC-Lab/
├── include/ppclab/ppc/   reusable public C++ API
├── src/                  CPU, memory, loaders, execution, runtime stubs
├── tools/                ppc-lab CLI
├── scripts/              build, verification, diff/result tooling
├── tests/                synthetic deterministic regressions
├── profiles/             target-specific metadata/scripts/expectations
├── docs/                 usage, format, architecture, development docs
├── Tools/                convenient shell entry points
├── .github/workflows/    CI
├── CONTRIBUTING.md
└── LICENSE
```

## Documentation

| Document | What it answers |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | How do I get from clone to a useful execution quickly? |
| [`docs/BINARY_INTAKE.md`](docs/BINARY_INTAKE.md) | How do all native loaders fit together? |
| [`docs/ELF32.md`](docs/ELF32.md) | Exactly what ELF32 PPC does v0.3 accept? |
| [`docs/MACHO_PPC.md`](docs/MACHO_PPC.md) | What Mach-O PPC container/file/relocation behavior is supported? |
| [`docs/PEF_CFM.md`](docs/PEF_CFM.md) | How does PEF/CFM loading, pidata, imports, exports, and relocation work? |
| [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) | What commands/options/defaults/exit behavior exist? |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Where are the core/loader/backend/profile boundaries? |
| [`docs/ADDING_A_TARGET.md`](docs/ADDING_A_TARGET.md) | How do I add a new project without contaminating the core? |
| [`docs/RESEARCH_WORKFLOW.md`](docs/RESEARCH_WORKFLOW.md) | How should PPC Lab be used alongside a decompiler? |
| [`docs/RESULT_FORMAT.md`](docs/RESULT_FORMAT.md) | What does deterministic JSON/dump output contain? |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | How do I add an opcode, relocation, loader feature, or backend? |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | What is left before v1.0? |
| [`docs/HISTORY.md`](docs/HISTORY.md) | Where did PPC Lab come from? |

## Hard architecture rules

1. **No target owns PPC Lab.** Target names, addresses, proprietary bytes, and
   application-specific runtime assumptions stay out of generic core code.
2. **Loaders parse formats; profiles express policy.** Reusable format mechanics
   belong in loaders. Target-specific imports and runtime behavior belong in
   profiles or explicit CLI bindings.
3. **Unsupported behavior fails visibly.** PPC Lab should stop rather than
   silently invent relocation, ABI, syscall, or CPU behavior.
4. **Every new capability gets a synthetic regression.** We should be able to
   improve this tool years from now without wondering which old project broke.
5. **PPC Lab is infrastructure, not a schedule.** Build the next capability when
   an actual reverse-engineering target needs it.

## Scope

PPC Lab v0.3 is a **PPC32 big-endian research execution platform**, not a full
Mac OS, Linux, console, or firmware emulator. Loader support does not imply that
the target operating system/runtime has been emulated. Dynamic-linker-heavy,
scattered/complex relocations, missing CPU instructions, syscalls, traps, or
runtime services may still stop execution; those stops are intentionally
observable research tasks.

## License and target binaries

PPC Lab source, scripts, tests, and repository profiles are distributed under
GNU GPL version 3 only. Externally supplied binaries being analyzed are inputs
to the tool. PPC Lab does not bundle, redistribute, or relicense proprietary
software merely because a user points the harness at it.
