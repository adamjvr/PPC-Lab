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

## v1.9.0 — Guided Exploration & Corpus Synthesis

v1.9 turns known PPC call inputs into a deterministic discovery frontier. `ppc-lab-explore` varies explicit register/write/binding/syscall domains, keeps only executions that add dynamic PC coverage or a new stable architectural outcome, and can promote successful novel cases directly into the behavioral corpus without copying private target binaries.

```bash
ppc-lab-explore explore.json --out ./explore-run
ppc-lab-explore explore.json --out ./explore-run --promote-corpus ./corpus
```

See [`docs/EXPLORATION.md`](docs/EXPLORATION.md).

## v1.8.0 — Automated Differential Triage

v1.8 turns backend/version disagreements into compact research artifacts. `ppc-lab-triage` can compare existing `ppc-lab-trace-v1` files or execute the same stable worker job against two engine/backend configurations, then report the common prefix, first divergent instruction/control-flow point, resynchronization point, snapshot differences, and a reduced instruction-budget repro. Triage bundles contain evidence and input hashes, **not target binaries**.

```bash
ppc-lab-triage run job.json \
  --left-backend builtin --right-backend unicorn \
  --bundle ./triage-case --json ./triage-case.json

ppc-lab-triage compare old.trace.json new.trace.json \
  --bundle ./trace-diff --fail-on-diff
```

## v1.7.0 — Behavioral Corpus & Replay

v1.7 turns one-off successful experiments into portable long-lived behavioral regressions. `ppc-lab-corpus` fingerprints every binary input, records stable execution expectations, replays cases across engine versions/backends, verifies embedded redistributable fixtures, and can explicitly bless intentional behavior changes or minimize a failing setup. Proprietary target binaries remain external unless `--embed-input` is deliberately requested.

```bash
ppc-lab-corpus promote ./corpus --id constructor-001 --job job.json --tag constructor
ppc-lab-corpus replay ./corpus --input-root /srv/private-targets --backend builtin
ppc-lab-corpus verify ./corpus
```

See [`docs/BEHAVIORAL_CORPUS.md`](docs/BEHAVIORAL_CORPUS.md).

## v1.6.0 — Trace Intelligence & Coverage Analytics

v1.6 turns portable instruction traces into hot-PC/function reports, observed basic blocks/control-flow/calls, dynamic coverage summaries, Graphviz CFGs, and A/B trace diffs. Existing trace archives remain valid and the new analytics can flow into the evidence store and decompiler evidence.

```bash
ppc-lab-trace-capture --ppc-lab ppc-lab --json /tmp/run.trace.json -- --image target.bin --entry-symbol interesting --backend builtin
ppc-lab-trace-analyze /tmp/run.trace.json --json /tmp/run.analysis.json --dot /tmp/run.dot
ppc-lab-trace-diff baseline.trace.json /tmp/run.trace.json --json /tmp/run.diff.json
```

See [`docs/TRACE_ANALYTICS.md`](docs/TRACE_ANALYTICS.md).

## v1.5.0 — Research API Service

v1.5 adds a small standard-library HTTP transport for deployments that cannot conveniently use local pipes, persistent SSH streams, or the fleet controller. `ppc-lab-api` keeps the existing `ppc-lab-job-v1` / `ppc-lab-worker-response-v1` execution contract intact and exposes read-only evidence queries over the same server process. It binds to loopback by default and requires bearer authentication before non-loopback binding.

```bash
export PPC_LAB_API_TOKEN='replace-with-a-random-secret'
ppc-lab-api --root /srv/ppc-work --evidence-store /srv/ppc-evidence
```

For remote use, keep the API on loopback behind an SSH tunnel or TLS reverse proxy. See [`docs/HTTP_API.md`](docs/HTTP_API.md).

## v1.4.0 — Evidence Server & Result Index

v1.4 closes the loop between large server/fleet runs and long-lived reverse-engineering research. `ppc-lab-evidence` ingests PPC Lab JSON result directories into a content-addressed object store plus a local SQLite index, deduplicates semantic duplicates, preserves source/raw hashes, and makes old runs queryable by engine, backend, host, result status, cache key, or target-input SHA-256. It stores **evidence JSON, not proprietary target binaries**.

```bash
ppc-lab-evidence init /srv/ppc-evidence
ppc-lab-evidence ingest /srv/ppc-evidence /srv/results/run-001
ppc-lab-evidence query /srv/ppc-evidence --input-sha256 8f31d9 --ok yes
ppc-lab-evidence report /srv/ppc-evidence
ppc-lab-evidence verify /srv/ppc-evidence
```

Or publish automatically when a run finishes:

```bash
ppc-lab-fleet fleet.json --out /srv/results/run-002 --evidence-store /srv/ppc-evidence
```

See [`docs/EVIDENCE_STORE.md`](docs/EVIDENCE_STORE.md) for storage, query, integrity, provenance, and privacy/copyright boundaries.

## v1.3.0 — Distributed Worker Fleet

v1.3 takes the stable server worker/orchestration stack across multiple machines without adding a daemon, database, cloud SDK, or bespoke network protocol. `ppc-lab-fleet` capability-probes local/OpenSSH workers, enforces one engine version, stages binary inputs by SHA-256, respects per-host slots/tags/backend availability, retries transient transport/time-out failures on another compatible host, and preserves deterministic result/cache identity.

```bash
ppc-lab-fleet fleet.json \
  --local-root /srv/research \
  --out /srv/results/run-001 \
  --cache /srv/cache/ppc-lab
```

See [`docs/FLEET.md`](docs/FLEET.md) for the manifest, SSH deployment, staging, retry, cache, and security contracts.

## v1.2.0 — Parallel Server Orchestration

v1.2 makes the server-side platform practical for large experiment sets without turning PPC Lab into a daemon project. `ppc-lab-orchestrate` consumes a `ppc-lab-orchestration-v1` manifest of stable v1 worker jobs, executes them concurrently, writes atomic per-job evidence, resumes matching prior results, and optionally reuses successful work through deterministic content-addressed cache keys.

```bash
ppc-lab-orchestrate manifest.json \
  --out results/run-001 \
  --cache /srv/ppc-cache \
  --root /srv/ppc-work \
  --parallel 16
```

Cache identity includes the canonical job, PPC Lab engine identity, and SHA-256 of target inputs; changing the binary bytes invalidates cached work automatically. See [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).

## v1.1.0 — Server Worker Protocol

v1.1 promotes PPC Lab's original server-side use case to a stable transport boundary. `ppc-lab-worker` accepts `ppc-lab-job-v1` JSON, executes it through the installed PPC Lab engine, and returns `ppc-lab-worker-response-v1` with deterministic result and snapshot evidence inline. Streaming mode uses NDJSON and is designed to survive individual guest failures without restarting the worker.

The worker intentionally stays transport-neutral and dependency-light: pipe it locally, keep it open over SSH, run it in CI/container workers, or wrap it in infrastructure owned by the deployment. PPC Lab v1.1 itself did not require a service transport; v1.5 later adds an optional standard-library HTTP adapter while preserving the worker protocol as the execution boundary.

```bash
ppc-lab-worker --root /srv/ppc-work run /srv/ppc-work/jobs/probe.json
ssh ppc-host 'ppc-lab-worker --root /srv/ppc-work stream'
```

See [`docs/WORKER_PROTOCOL.md`](docs/WORKER_PROTOCOL.md) and the machine-readable contracts under [`schemas/`](schemas/).

## v1.0.0 — General PPC Research Platform

v1.0 closes the original roadmap promise: for a supported native container, you can hand PPC Lab the file itself, inspect it, choose a routine, execute it deterministically, bind/stub its environment, capture evidence, and feed that evidence back into decompilation without building target-specific execution infrastructure first.

The v1.0 release adds:

- a reusable `UniversalImageLoader` core that auto-detects ELF32 PPC, PPC32 Mach-O, and PowerPC PEF/CFM;
- `--image FILE` for auto-detected disassembly/execution, plus `run` as an alias for `call`;
- one-command `analyze`, machine-readable `capabilities --json`, and `doctor` diagnostics;
- a proper installed C++ package (`find_package(PPCLab CONFIG)`, `PPCLab::core`) alongside the CLI;
- an external-consumer install regression, so the public API is tested from outside the source tree;
- a single version source in CMake and explicit v1 compatibility/stability documentation.

PPC Lab remains intentionally **PPC32 big-endian first**. v1.0 is a stable research platform, not a claim to emulate every PowerPC CPU, operating system, or runtime. Missing behavior stays visible and demand-driven.

## Fast start

```bash
./Tools/verify.command
./build/release/ppc-lab selftest --backend builtin
```

Triage any supported native image without executing it:

```bash
./build/release/ppc-lab analyze target.bin
./build/release/ppc-lab symbols target.bin
./build/release/ppc-lab metadata target.bin > target.metadata.json
```

Then use the v1 fast path—no format switch required:

```bash
./build/release/ppc-lab disasm --image target.bin --count 32
./build/release/ppc-lab run --image target.bin --backend builtin
```

Explicit `--elf`, `--macho`, and `--pef` switches remain supported when a script wants to assert one exact container type.

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
  --json /tmp/result.json \
  --snapshot /tmp/state.json
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
- import traps, structured traps/syscalls, deterministic syscall-return bindings, and explicit symbol bindings;
- reusable runtime stubs for libm, memory operations, and Classic Mac block moves;
- instruction limits, symbol-aware trace output, trace ranges, dynamic coverage/CFG analytics, and A/B trace diffing;
- memory dumps with FNV-1a64 fingerprints;
- machine-readable results, normalized metadata, and deterministic full-state snapshots;
- byte/float comparison, snapshot diffing, batch sweeps, and differential execution;
- synthetic loader/relocation/execution regressions plus property/malformed-input stress coverage;
- GPL/SPDX/version/target-neutrality repository invariants;
- stable JSON/NDJSON server-worker protocol for remote/headless execution;
- parallel/resumable server orchestration with deterministic content-addressed execution caching;
- multi-host local/OpenSSH fleet execution with capability negotiation, SHA-256 staging, host slots/tags, and failover;
- content-addressed evidence storage/indexing with semantic JSON deduplication, provenance, queries, reports, and integrity verification;
- low-maintenance macOS/Linux/Windows CI.

The original external Classic Mac regression remains preserved as a target
profile: the ReBirth Distortion constructor has a known successful 133,027-
instruction run and object fingerprint, but no proprietary bytes are included in
PPC Lab.

## Commands

```text
ppc-lab doctor
ppc-lab capabilities [--json]
ppc-lab selftest [--backend auto|builtin|unicorn]
ppc-lab analyze FILE [--json] [--symbols]
ppc-lab image-info FILE
ppc-lab symbols FILE
ppc-lab metadata FILE [--image-base HEX] [--bind NAME=ADDRESS]
ppc-lab disasm (--image FILE | --code FILE | --elf FILE | --macho FILE | --pef FILE) ...
ppc-lab call|run (--image FILE | --code FILE | --elf FILE | --macho FILE | --pef FILE) ...
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

## Install / consume as a library

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel
cmake --install build/release --prefix "$HOME/.local"
```

Downstream CMake projects can use:

```cmake
find_package(PPCLab 1.0 CONFIG REQUIRED)
target_link_libraries(my_tool PRIVATE PPCLab::core)
```

See [`docs/INSTALLATION.md`](docs/INSTALLATION.md) and [`docs/STABILITY.md`](docs/STABILITY.md).

## Repository layout

```text
PPC-Lab/
├── include/ppclab/ppc/   reusable public C++ API
├── src/                  CPU, memory, loaders, execution, runtime stubs
├── tools/                ppc-lab CLI
├── scripts/              worker/orchestration/fleet/evidence, experiments, trace/diff tooling
├── runtimes/             reusable runtime personality maps
├── integrations/         Ghidra / IDA / Binary Ninja evidence adapters
├── tests/                synthetic deterministic regressions
├── profiles/             target-specific metadata/scripts/expectations
├── docs/                 usage, format, architecture, development docs
├── schemas/              stable worker/orchestration/fleet JSON contracts
├── Tools/                convenient shell entry points
├── .github/workflows/    CI
├── CONTRIBUTING.md
└── LICENSE
```

## Documentation

| Document | What it answers |
|---|---|
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | How do I get from clone to a useful execution quickly? |
| [`docs/WORKER_PROTOCOL.md`](docs/WORKER_PROTOCOL.md) | How do I submit stable JSON jobs locally, over SSH, or from server infrastructure? |
| [`docs/BEHAVIORAL_CORPUS.md`](docs/BEHAVIORAL_CORPUS.md) | How do I promote experiments into replayable long-lived regressions? |
| [`docs/DIFFERENTIAL_TRIAGE.md`](docs/DIFFERENTIAL_TRIAGE.md) | How do I isolate and bundle the first backend/version behavioral divergence? |
| [`docs/HTTP_API.md`](docs/HTTP_API.md) | How do I expose worker execution and evidence queries through the optional HTTP service? |
| [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) | How do I run, resume, and cache large parallel server experiment sets? |
| [`docs/FLEET.md`](docs/FLEET.md) | How do I distribute stable jobs across local/OpenSSH PPC Lab hosts? |
| [`docs/EVIDENCE_STORE.md`](docs/EVIDENCE_STORE.md) | How do I index, query, deduplicate, and verify long-lived PPC Lab evidence? |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | How do I install the CLI/core package or consume it from CMake? |
| [`docs/STABILITY.md`](docs/STABILITY.md) | What compatibility promises start at v1.0? |
| [`docs/BINARY_INTAKE.md`](docs/BINARY_INTAKE.md) | How do all native loaders fit together? |
| [`docs/ELF32.md`](docs/ELF32.md) | What ELF32 PPC intake/relocation behavior is supported? |
| [`docs/MACHO_PPC.md`](docs/MACHO_PPC.md) | What Mach-O PPC container/file/relocation behavior is supported? |
| [`docs/PEF_CFM.md`](docs/PEF_CFM.md) | How does PEF/CFM loading, pidata, imports, exports, and relocation work? |
| [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md) | What commands/options/defaults/exit behavior exist? |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Where are the core/loader/backend/profile boundaries? |
| [`docs/ADDING_A_TARGET.md`](docs/ADDING_A_TARGET.md) | How do I add a new project without contaminating the core? |
| [`docs/RESEARCH_WORKFLOW.md`](docs/RESEARCH_WORKFLOW.md) | How should PPC Lab be used alongside a decompiler? |
| [`docs/RESULT_FORMAT.md`](docs/RESULT_FORMAT.md) | What does deterministic JSON/dump output contain? |
| [`docs/METADATA.md`](docs/METADATA.md) | How do external tools consume normalized loader metadata? |
| [`docs/RUNTIMES.md`](docs/RUNTIMES.md) | How do reusable import/runtime personalities work? |
| [`docs/SNAPSHOTS.md`](docs/SNAPSHOTS.md) | What is captured in deterministic behavioral state? |
| [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) | How do batch sweeps and differential runs work? |
| [`docs/DECOMPILER_INTEGRATION.md`](docs/DECOMPILER_INTEGRATION.md) | How do Ghidra, IDA, and Binary Ninja consume evidence? |
| [`docs/ISA_COVERAGE.md`](docs/ISA_COVERAGE.md) | What PPC32 instruction behavior is covered and what is intentionally approximate? |
| [`docs/EXCEPTIONS_SYSCALLS.md`](docs/EXCEPTIONS_SYSCALLS.md) | How are `sc`, `tw`, and `twi` surfaced or stubbed? |
| [`docs/TESTING_FUZZING.md`](docs/TESTING_FUZZING.md) | What parity, property, malformed-input, and sanitizer tests protect the engine? |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | How do I add an opcode, relocation, loader feature, or backend? |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | What remains deliberately post-1.0 and demand-driven? |
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

PPC Lab v1.x is a **PPC32 big-endian research execution platform**, not a full
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
