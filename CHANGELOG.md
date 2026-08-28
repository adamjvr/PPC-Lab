# Changelog

## 1.1.0 — 2026-08-27 — Server Worker Protocol

- Added `ppc-lab-worker`, a standard-library JSON/NDJSON execution adapter for server, SSH, CI, container, and subprocess deployments.
- Added stable `ppc-lab-job-v1` and `ppc-lab-worker-response-v1` contracts so client projects do not need to construct PPC Lab CLI arguments directly.
- Worker responses embed the existing deterministic result and full snapshot formats, preserving v1 research evidence across transport boundaries.
- Added `--root` filesystem containment, symlink-safe path resolution, per-job wall-clock timeouts, and optional command exposure for deployment/debugging policy.
- Added machine-readable JSON Schema files and capability discovery for the worker protocols.
- Added one-shot, failed-execution, root-containment, resilient NDJSON stream, and malformed-transport regressions.
- Install trees now include `ppc-lab-worker` and the protocol schemas alongside the CLI/core package.

## 1.0.0 — 2026-08-27 — General PPC Research Platform

- Added `UniversalImageLoader`, a reusable core auto-detection/loading boundary for supported ELF32 PPC, Mach-O PPC32, and PEF/CFM images.
- Added `--image FILE` to `call`/`run` and `disasm`; explicit format switches remain available for scripts that want them.
- Added `run` as a readable alias for `call`.
- Added `analyze FILE` for one-command format/entry/symbol triage.
- Added `capabilities [--json]` for automation/decompiler/tool discovery and `doctor` for executable/backend self-diagnostics.
- Made the CMake project version the CLI version source of truth rather than duplicating release strings in code.
- Added a complete install/export contract: CLI, static core library, public headers, docs, `PPCLabConfig.cmake`, version file, and exported `PPCLab::core` target.
- Added an install-contract regression that installs PPC Lab into a clean prefix, runs the installed CLI, discovers it with `find_package(PPCLab CONFIG)`, and compiles a downstream C++ consumer.
- Promoted the binary-intake CLI regressions to exercise auto-detected ELF, Mach-O, and PEF execution paths.
- Added v1.0 installation and stability/compatibility documentation and updated the quick start, architecture, binary-intake, CLI, and roadmap contracts.
- v1.0 remains intentionally PPC32 big-endian first; PPC64, little-endian PowerPC, deeper OS personalities, JIT/debugger-server work, and richer decompiler plugins remain demand-driven post-1.0 capabilities.

## 0.5.0 — 2026-08-27 — PPC Coverage Monster

- Expand builtin PPC32 execution across common integer, rotate, CR logical, update-indexed, byte-reversed, atomic reservation, cache/order, multiply/divide overflow, and floating-point instruction families.
- Add structured `sc`, `tw`, and `twi` stop reasons plus deterministic `--syscall-return`, `--default-syscall-return`, and `--ignore-traps` controls.
- Improve XER SO/OV/CA and selected FP record/FPSCR-to-CR behavior used by the new instruction coverage.
- Expand lightweight disassembly for the newly executable instruction families.
- Add execution-coverage, property/stress, malformed binary-intake, and optional builtin-vs-Unicorn backend-parity regressions.
- Document the PPC32 coverage/fidelity boundary and explicit syscall/trap research contract.

## 0.4.0 — 2026-08-27 — Research Machine

- Carry native image symbols into execution so `--trace` is symbol-aware without a separate post-processing step.
- Add `metadata` JSON intake output for decompiler/tooling integration.
- Add deterministic `--snapshot` capture with full CPU state, memory-region fingerprints, image symbols, and requested dumps.
- Add reusable runtime personalities and automatic import binding/stubbing for minimal Classic Mac and libc/POSIX research.
- Expand built-in behavioral stubs with memcpy/memmove/memset/bzero and fabs/floor/ceil.
- Add dependency-free batch parameter sweeps, snapshot comparison, differential execution, trace capture, and evidence packaging.
- Add Ghidra, IDAPython, and Binary Ninja evidence import helpers.
- Add regression coverage for runtime stubs and the complete research-tool workflow.

## 0.3.0 — 2026-08-26 — Binary Intake Blitz

- Added native PEF/CFM PowerPC parsing, section instantiation, pattern-initialized data, import/export metadata, main/init/term discovery, and standard relocation-bytecode execution.
- Added thin and fat 32-bit big-endian PowerPC Mach-O intake for objects, executables, dylibs, and bundles, including symbol parsing, entry discovery, and common PowerPC relocations.
- Expanded ELF32 PowerPC intake from fixed ET_EXEC files to ET_EXEC, ET_DYN, and ET_REL with section/symbol parsing, rebasing, and common System V PowerPC relocation types.
- Added explicit `--bind NAME=ADDRESS`, `--entry-symbol`, and `--image-base` controls so target-specific linking policy stays outside the generic core.
- Added auto-detecting `image-info` and `symbols` commands plus Mach-O/PEF support in `call` and `disasm`.
- Added synthetic end-to-end regression fixtures for ELF relocatable objects, Mach-O executables, and PEF relocation streams.


## 0.2.0 — 2026-08-26

- Added a dependency-free ELF32 big-endian PowerPC `ET_EXEC` loader.
- Added automatic `PT_LOAD` virtual-address mapping, ELF-derived permissions, and BSS zero-fill.
- Added `ppc-lab elf-info FILE` for safe executable-image inspection.
- Added `ppc-lab disasm` for raw and ELF-backed lightweight instruction inspection.
- Added `ppc-lab call --elf FILE`; ELF `e_entry` is used by default and explicit entry/CFM transition-vector overrides remain available.
- Kept raw relocated-image and Classic CFM workflows backward-compatible.
- Expanded the built-in disassembly text for common integer, branch, load/store, SPR, and floating-point instructions.
- Added synthetic ELF loader tests and an end-to-end CLI regression that inspects, disassembles, and executes a generated PPC ELF.
- Added dedicated ELF32 documentation and a demand-driven long-term roadmap.

## 0.1.1 — 2026-08-26

- Licensed PPC Lab under GNU GPL version 3.0 only (`GPL-3.0-only`).
- Added the full GPLv3 license text and SPDX identifiers across source, build, CI, and script files.
- Expanded README and architecture documentation.
- Added quick-start, CLI reference, result-format, research-workflow, and development guides.
- Expanded target-profile guidance and documented the boundary between GPL repository material and externally supplied target binaries.
- Added contributor guidance for low-maintenance, target-driven development.
- Added a cross-platform repository-invariant test enforcing GPL/SPDX markings and the target-neutral core boundary.

## 0.1.0 — 2026-08-26

- Extracted the proven PPC execution harness from X0X:ReAnimated into standalone PPC Lab.
- Preserved dependency-free PPC32-BE and optional Unicorn backends.
- Generalized namespace, CLI, CMake project, result schemas, and address controls.
- Replaced target-hardcoded import addresses with runtime `--stub KIND@ADDRESS` bindings.
- Preserved ReBirth as an external-byte regression profile.
- Added macOS/Linux helper commands and three-OS GitHub CI.
