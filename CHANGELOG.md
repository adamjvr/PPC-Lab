# Changelog

## 1.6.0 — 2026-08-28 — Trace Intelligence & Coverage Analytics

- Add installed `ppc-lab-trace-capture`, `ppc-lab-trace-analyze`, and `ppc-lab-trace-diff` commands while preserving `ppc-lab-trace-v1`.
- Add dynamic PC coverage, instruction/mnemonic frequency, symbol/function hotness, observed basic blocks/control-flow edges, and inferred calls.
- Add Graphviz DOT export and machine-readable `ppc-lab-trace-analysis-v1`.
- Add `ppc-lab-trace-diff-v1` with coverage Jaccard and per-PC/function/call deltas plus optional CI failure mode.
- Feed analyses/diffs into the evidence store and hot-block/call annotations into decompiler-neutral evidence.
- Advertise/install the schemas and add end-to-end capture/analyze/diff/install regression coverage.

## 1.5.0 — 2026-08-28 — Research API Service

- Add `ppc-lab-api`, a dependency-free threaded HTTP transport over the stable v1 worker/evidence contracts.
- Add authenticated `POST /v1/run`, health/discovery/capability endpoints, and read-only evidence query/report/artifact endpoints.
- Bind to loopback by default; require bearer authentication for non-loopback binds unless a deliberately dangerous override is supplied.
- Preserve worker filesystem and wall-clock containment, add bounded request bodies, and keep guest failures distinct from HTTP/transport failures.
- Add atomic ready-file output for service supervisors/tests and advertise `ppc-lab-http-api-v1` through capability discovery.
- Add API ready/health/discovery schemas, install-tree coverage, end-to-end HTTP/auth/execution/evidence regressions, and deployment/security documentation.
- Keep TLS, public-internet exposure, and evidence ingestion outside the built-in service boundary; use SSH tunnels or a maintained TLS reverse proxy for remote deployment.

## 1.4.0 — 2026-08-28 — Evidence Server & Result Index

- Add `ppc-lab-evidence`, a standard-library content-addressed JSON evidence store backed by local SQLite indexing.
- Index worker, orchestration, fleet, result, snapshot, metadata, and other `ppc-lab-*` JSON evidence without copying target binaries into the store.
- Deduplicate semantically identical JSON regardless of whitespace/key ordering; preserve every source path/raw SHA-256 as provenance.
- Add indexed query filters for schema, engine version, backend, stop reason, host, name, success, cache-key prefix, and input SHA-256 prefix.
- Add artifact lookup, aggregate reporting, and full object/hash verification with missing/corrupt/orphan detection.
- Add optional `--evidence-store` publication to local orchestration and distributed fleet runs.
- Add stable evidence query/report/verify v1 schemas, installed tooling, capability advertising, documentation, and end-to-end evidence-store regressions.
- Preserve the low-maintenance server architecture: SQLite is a local index file, not a daemon/database service, and target binaries remain external unless explicitly handled by project-owned infrastructure.

## 1.3.0 — 2026-08-27 — Distributed Worker Fleet

- Add `ppc-lab-fleet`, a dependency-free scheduler for local and OpenSSH worker fleets.
- Add capability/version negotiation, per-host slots and tags, deterministic job placement, and backend eligibility.
- Add SHA-256 content-addressed input staging for local/remote workers, central result caching, exact resume, and transient retry/failover.
- Add fleet manifest/result/summary v1 schemas and local multi-host regression coverage.
- Preserve `ppc-lab-job-v1` / `ppc-lab-worker-response-v1` as the execution boundary; the fleet layer does not introduce a daemon or web service.

## 1.2.0 — 2026-08-27 — Parallel Server Orchestration

- Added `ppc-lab-orchestrate`, a dependency-free parallel scheduler above the stable `ppc-lab-job-v1`/worker boundary.
- Added `ppc-lab-orchestration-v1` manifests supporting inline jobs and referenced standalone job files with stable per-file relative-path semantics.
- Added bounded concurrent execution, atomic per-job evidence records, deterministic summaries, and continuation after individual guest failures.
- Added `--resume` for interrupted result directories; reuse requires an exact current cache key rather than trusting filenames.
- Added optional shared content-addressed caching keyed by canonical job JSON, PPC Lab engine identity, and SHA-256/size of every input binary/data file.
- Added cache bypass controls and successful-result-only cache writes so failed research cases are not silently treated as completed infrastructure.
- Added orchestration-root checks before input hashing, while retaining the worker's independent symlink-safe execution containment.
- Added worker `--base-dir` for stdin/NDJSON relative-path resolution without conflating path resolution with filesystem containment.
- Added orchestration/summary JSON Schemas, installed orchestrator tooling, machine-readable capability advertising, documentation, examples, and end-to-end parallel/resume/cache invalidation regressions.

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
