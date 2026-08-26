# Changelog

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
