## 3.3.0 — 2026-08-28 — LTS Diagnostics & Supportability

- Add installed `ppc-lab-support diagnose/bundle/verify` for target-neutral whole-install diagnostics and auditable support artifacts.
- Collect core doctor/capabilities, companion readiness, compatibility declarations, optional persisted-state/evidence/knowledge integrity, control-plane telemetry, and recent failed campaign records.
- Add bounded UTF-8 text-log collection with secret and declared-root redaction; usernames, hostnames, environment dumps, persisted databases, and target bytes are excluded by design.
- Add restricted `ppc-lab-support-bundle-v1` archives containing only a support report, SHA-256 manifest, and optional redacted text logs; verification rejects unexpected members or modified payloads.
- Add `ppc-lab-support-report-v1`, install/capability/LTS invariant coverage, and dedicated supportability documentation.
- Preserve the post-v3 feature freeze: this release adds diagnostics/support infrastructure, not another PPC execution/runtime subsystem.

## 3.2.0 — 2026-08-28 — LTS Compatibility & Upgrade Assurance

- Add `ppc-lab-compat` snapshots and same-major baseline checks for public C++ API/ABI markers, stable schemas/tools, and persisted-state format levels.
- Add the checked-in v3.1.0 LTS compatibility baseline and dependency-free compatibility regression coverage.
- Embed the full compatibility declaration in reproducible `RELEASE-MANIFEST.json` output.
- Add read-only evidence/knowledge/control state compatibility auditing via the existing v3 platform migration contract.
- Add compatibility API metadata, installed schema/tool contracts, and thorough LTS compatibility documentation.
- Keep the post-v3 freeze intact: no new execution/runtime subsystem.

# Changelog

## 3.1.0 — 2026-08-28 — LTS Target SDK & Reproducible Releases

- Add installed `ppc-lab-target`, a dependency-free target-profile SDK for generating, validating, inspecting, and reproducibly packaging project adapters around the stable PPC Lab core.
- Add `ppc-lab-target-profile-v1` and `ppc-lab-target-profile-package-v1` contracts with explicit external-input declarations and a default no-private-binary packaging rule.
- Add installed `ppc-lab-release`, deterministic source-manifest/archive tooling using stable SHA-256 file inventories, normalized modes/timestamps, and embedded `RELEASE-MANIFEST.json`.
- Add `ppc-lab-release-manifest-v1` plus explicit C++ API/ABI and target-profile API version metadata through installed `ppclab/Version.hpp`.
- Extend capabilities, repository invariants, install/downstream package tests, and documentation to enforce the v3 LTS compatibility boundary.
- Keep v3.1 deliberately non-expansive: no new PPC execution/runtime subsystem; this release reduces future maintenance and target-integration friction.

## 3.0.0 — 2026-08-28 — Mature Platform Consolidation

- Added installed `ppc-lab-platform` as the consolidated operator surface for whole-install status/doctor, persisted-state upgrade checks/migrations, and mature-platform acceptance.
- Added structural compatibility auditing for evidence stores, knowledge graphs, and filesystem control-plane state; unknown/incompatible schemas are rejected instead of guessed.
- Added idempotent v3 persisted-state migration metadata with first-run safety backups for evidence SQLite, knowledge SQLite, and control-plane JSON state.
- Added stable `ppc-lab-platform-status-v1`, `ppc-lab-upgrade-report-v1`, and `ppc-lab-acceptance-report-v1` schemas and capability/install contracts.
- Added a synthetic release acceptance scenario spanning ELF32 PPC intake, real builtin execution, deterministic exploration, evidence verification, evidence-gated hypothesis promotion, and knowledge-graph ingestion/query.
- Added major-release documentation for platform operations, upgrades, archive certification, and the post-v3 target-driven maintenance boundary.
- Bumped the installed CMake package to major version 3; downstream consumers should request `find_package(PPCLab 3.0 CONFIG REQUIRED)`.
- Preserved all existing v1/v2 execution/research schema meanings and the no-private-binary archival rule.

## 2.5.0 — 2026-08-28 — Automated Hypothesis Engine

- Added installed `ppc-lab-hypothesize`, a deterministic evidence-first hypothesis engine over PPC Lab exploration results.
- Added transparent role inference for boolean/selector/count/pointer/scalar call inputs, floating arguments, probed state fields, import bindings, and environment/syscall results.
- Added explicit confidence, supporting/contradicting case IDs, behavior fingerprints, coverage/behavior partitions, failure evidence, and instruction-count correlation metrics.
- Added bounded follow-up experiment generation as ordinary `ppc-lab-exploration-v1` manifests rather than a separate execution path.
- Added evidence-gated promotion with content-pinned exploration cases, configurable confidence/support thresholds, and tamper detection; candidates are never auto-promoted.
- Added knowledge-graph hypothesis nodes, target/behavior/address relationships, and supported state-field annotations for decompiler export.
- Added stable hypothesis report/experiment/promoted-record schemas, capability/install contracts, documentation, and end-to-end regression coverage.
- Preserved the no-target-binary rule: hypothesis artifacts contain target hashes/provenance and research evidence, never private input bytes.

## 2.4.0 — 2026-08-28 — Research Knowledge Graph

- Added dependency-free `ppc-lab-knowledge` SQLite relationship graph over accumulated PPC Lab JSON research artifacts.
- Added SHA-256 target identity and target-scoped symbol/function/address relationships without copying private target binaries.
- Added cross-target stable behavior and dynamic coverage fingerprint nodes for “where have we seen this before?” research queries.
- Added corpus-case, differential-triage, campaign, symbol, execution, call-edge, and manual-annotation relationship ingestion.
- Added direct synchronization from existing v1.4 evidence stores.
- Added node filtering, related-neighborhood traversal, shortest relationship paths, graph reports, and integrity verification.
- Added decompiler-neutral aggregate export back to `ppc-lab-evidence-v1` for the existing Ghidra/IDA/Binary Ninja adapters.
- Added five stable v2.4 graph query/report/traversal/verification schemas and install/capability contracts.
- Added end-to-end regression coverage for cross-target shared behavior, evidence synchronization, graph paths, and decompiler export.

## 2.3.0 — 2026-08-28 — Campaign Control Plane

- Add installed `ppc-lab-control`, a dependency-free persistent queue/supervisor above `ppc-lab-schedule`.
- Add durable scheduler-run submission with deterministic priority/sequence ordering, SHA-256 revalidation at dispatch, bounded active scheduler processes, and exact scheduler `--resume` reuse when checkpoint state already exists.
- Add live atomic telemetry with queue counts, active scheduler PIDs/liveness, uptime, scheduler campaign counts, campaign subprocess PIDs, project/event counts, and history depth.
- Add supervisor-friendly pause/resume/drain, per-run cancellation, and global cancellation without replacing the scheduler/campaign control markers underneath.
- Add append-only terminal run history plus per-run history records carrying manifest SHA-256, attempts, timestamps, output paths, return codes, and scheduler summaries without copying target binaries.
- Add single-supervisor locking, conservative orphan-process detection after hard supervisor failure, concurrent-writer-safe atomic JSON replacement, stable control/item/telemetry/history-list/history-record v1 schemas, capability advertising, install coverage, documentation, and end-to-end control-plane regression tests.

## 2.2.0 — 2026-08-28 — Campaign Scheduling & Resource Governance

- Add installed `ppc-lab-schedule`, a dependency-free scheduler above the existing autonomous-campaign command.
- Add deterministic weighted fair-share between projects, priority ordering within projects, global and per-project concurrency caps, project case-budget admission quotas, and process wall-time accounting.
- Add exact manifest-hash resume semantics; terminal completed/failed/cancelled/quota-blocked admissions are not reconsidered, while interrupted running campaigns return to pending and reuse campaign-level `--resume` when state exists.
- Add filesystem `DRAIN`, global `CANCEL`, and per-campaign cancel markers for supervisor-friendly graceful control without adding another daemon or service dependency.
- Add stable scheduler manifest/state/summary v1 schemas, capability advertising, install-tree coverage, documentation, and a synthetic regression covering fair share, priority, quotas, cancellation, and the terminal-resume bug.

## 2.1.0 — 2026-08-28 — Campaign Intelligence & Prioritization

- Add deterministic adaptive exploration that reorders mutation axes by observed novelty/coverage yield and can conserve unused case budget when a configured novelty plateau is reached.
- Add `ppc-lab-prioritize` with transparent case scoring, rare-PC weighting, axis/value yield summaries, deterministic ranking, plateau analysis, and machine-readable `ppc-lab-priority-report-v1`.
- Add an optional `intelligence` block to `ppc-lab-campaign-v1`; campaigns now checkpoint an intelligence stage and priority-order eligible differential-triage cases before applying `max_triage_cases`.
- Publish intelligence JSON alongside exploration/triage/corpus evidence and report `exploration-saturated` as a normal research finding rather than an infrastructure failure.
- Add stable priority-policy/report schemas, capability advertising, install-tree coverage, adaptive-exploration regression coverage, campaign-intelligence tests, and updated documentation.

## 2.0.0 — 2026-08-28 — Autonomous Research Campaigns

- Add `ppc-lab-campaign`, a standard-library composition layer that drives guided exploration, behavioral-corpus promotion/verification/replay, differential triage, and evidence publication as one bounded research lifecycle.
- Add manifest-hash + engine-version checkpoint state and exact `--resume` semantics so interrupted campaigns can continue without silently changing their research conditions.
- Add `--dry-run` planning/root validation that resolves target inputs and engine capabilities without executing guest code.
- Add campaign budgets for exploration cases, triage cases, per-case wall time, and optional overall wall time while preserving each guest job's independent instruction limit.
- Add automatic triage selection for novel, failed, novel-or-failed, or all exploration cases and support a second installed engine/worker for cross-version differential campaigns.
- Add automatic evidence-store publication and verification after campaign artifacts are finalized; campaign/corpus/triage/evidence outputs preserve target hashes rather than copying target binaries.
- Add stable campaign manifest/state/summary/triage-summary v1 schemas, installed `ppc-lab-campaign`, capability advertising, comprehensive campaign documentation, and end-to-end resume/dry-run/root-safety regression coverage.
- Mark the v2 boundary as workflow autonomy above the stable execution primitives; the target-neutral C++ engine remains focused on PPC execution/intake rather than campaign policy.

## 1.9.0 — 2026-08-28 — Guided Exploration & Corpus Synthesis

- Add installed `ppc-lab-explore`, a deterministic exploration engine above the stable worker protocol.
- Add bounded guided BFS exploration where only coverage- or behavior-novel executions become parents for additional mutations.
- Add deterministic Cartesian exploration for deliberately small exhaustive domains.
- Restrict mutation axes to runtime register/write/binding/syscall inputs; structural image paths cannot be mutated through the explorer.
- Add stable behavior fingerprints, dynamic-PC novelty tracking, per-case evidence records, target SHA-256 provenance, and hard case-count bounds.
- Add optional direct promotion of successful novel cases into the behavioral corpus without copying target binaries.
- Add exploration manifest/case/summary v1 schemas, install/capability discovery, dedicated documentation, and end-to-end novelty/corpus/safety regressions.

## 1.8.0 — 2026-08-28 — Automated Differential Triage

- Add installed `ppc-lab-triage` for automated first-divergence analysis across PPC Lab traces, backends, and engine binaries.
- Identify the common execution prefix, first divergent PC/instruction, dynamic classification, bounded context window, and later trace resynchronization.
- Compare architectural snapshots while ignoring backend-label noise, surfacing CPU/memory-state differences separately from trace equality.
- Run one stable `ppc-lab-job-v1` against two engine/backend configurations through the existing worker protocol and capture trace/snapshot evidence automatically.
- Emit source-control-safe triage bundles containing traces, worker responses, report, provenance hashes, and a reduced instruction-budget `repro.job.json` without copying target binaries.
- Add `ppc-lab-differential-triage-v1` and `ppc-lab-triage-bundle-v1` schemas, capability discovery, install-contract coverage, documentation, and end-to-end regressions.

## 1.7.0 — 2026-08-28 — Behavioral Corpus & Replay

- Add `ppc-lab-corpus`, a standard-library behavioral regression corpus manager above the stable worker job/response contracts.
- Promote a job into a durable case by SHA-256 pinning every code/data input and recording backend-neutral stable result/snapshot expectations.
- Keep target binaries external by default; `--embed-input` is explicit and intended only for redistributable/synthetic fixtures.
- Replay selected cases/tags across current engine versions and builtin/Unicorn backends, emitting `ppc-lab-corpus-replay-summary-v1` machine-readable summaries.
- Resolve private inputs by explicit SHA-256 mapping or bounded input roots, verify bytes before execution, and stage them into temporary contained worker roots.
- Add corpus integrity verification, explicit `bless --yes` for intentional baseline changes, and failing-case setup minimization for initial register/write/binding state.
- Add corpus/case/replay JSON Schemas, installed tooling, capability discovery, documentation, and end-to-end promotion/replay/bless/minimize/corruption regressions.

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
