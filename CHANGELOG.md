# Changelog

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
