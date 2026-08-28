# Extraction history

PPC Lab v0.1.0 was extracted from the working `X0X-ReAnimated_2026-08-22_PPC_Harness_Phase1` milestone rather than rewritten from scratch.

The original harness had already demonstrated genuine external PowerPC execution: the relocated ReBirth Distortion constructor at `0x10000cf4` returned normally after 133,027 instructions under the dependency-free interpreter, and the first 128 object bytes produced FNV-1a64 `0x418c9e14a76a422e`.

During extraction:

- `x0x::ppc` became `ppclab::ppc`;
- the executable became `ppc-lab`;
- build options and result schemas were renamed;
- target-specific import addresses were removed from the core;
- import behaviors became address bindings supplied at invocation time;
- ReBirth addresses and validation moved to `profiles/rebirth/`;
- generic heap/stack/import/return address controls were exposed by the CLI;
- the previous synthetic and differential-result tests were retained and generalized.


## 0.1.1 licensing/documentation hardening — 2026-08-26

PPC Lab was explicitly published as free software under GNU GPL version 3.0 only (`GPL-3.0-only`). The repository gained the canonical GPLv3 license text, SPDX identifiers on source/build/script files, contributor guidance, and expanded quick-start, CLI, development, result-format, profile, architecture, and research-workflow documentation.

## v0.2.0 — first generic executable loader

The first post-extraction capability milestone added reusable ELF32 PowerPC
intake rather than another target-specific adapter. PPC Lab can now inspect,
disassemble, map, and execute fixed-address big-endian `EM_PPC` `ET_EXEC`
images directly. Synthetic ELF tests prove segment permissions, BSS zero-fill,
entry-point selection, CLI inspection/disassembly, and actual execution through
the normal call harness. Raw and Classic CFM workflows remain intact.

## v0.3.0 — Binary Intake Blitz — 2026-08-26

PPC Lab generalized binary intake in one concentrated milestone. ELF support expanded to `ET_DYN` and `ET_REL` with symbols and common System V PowerPC relocations; a native 32-bit PowerPC Mach-O loader added thin/fat intake, symbols, entry discovery, rebasing and common PPC relocations; and a native PEF/CFM loader added section instantiation, pattern-initialized data, imports/exports, main/init/term discovery, and standard relocation bytecode.

The CLI gained `image-info`, `symbols`, `--image-base`, `--entry-symbol`, and explicit `--bind` symbol resolution. Every native loader gained synthetic inspect/load/execute tests, and cross-format CLI tests prove that inspection, disassembly, and execution use the same generic `CallHarness` path.

## v0.4.0 — Research Machine — 2026-08-27

The binary-intake foundation was promoted into a repeatable behavioral-research
workflow. Native image symbols now flow into execution traces; the CLI emits
normalized intake metadata and complete deterministic state snapshots; reusable
minimal Classic Mac and libc/POSIX personalities automate understood import
stubs; and dependency-free scripts provide batch sweeps, snapshot comparison,
differential execution, trace capture, and evidence packaging. Thin adapters can
apply that portable evidence to Ghidra, IDA, and Binary Ninja without coupling
the PPC execution core to a decompiler API.


## v0.5.0 — PPC Coverage Monster — 2026-08-27

The builtin PPC32-BE engine received a concentrated execution-hardening pass:
common atomic, byte-reversed, update-indexed, CR logical, overflow-aware integer,
cache/order, and floating-point forms were added; traps and system calls became
structured execution boundaries; and disassembly grew alongside execution. The
regression suite added deterministic property/stress coverage, malformed native
image intake, and optional builtin-vs-Unicorn state parity. PPC64/little-endian
work was intentionally left out rather than diluting the stable PPC32-BE path.

## v1.0.0 — General PPC Research Platform — 2026-08-27

v1.0 unified native intake behind `UniversalImageLoader`, added the `--image`/`run` fast path, analysis/capability/doctor commands, and promoted PPC Lab to an installable C++ package with a tested downstream `find_package(PPCLab CONFIG)` contract. This marks completion of the original roadmap goal: a reusable, project-neutral PPC32-BE research platform that can accept supported binaries, isolate routines, model runtime boundaries, capture deterministic evidence, and feed results back into decompilation.

## v1.1.0 — Server Worker Protocol — 2026-08-27

v1.1 returned to PPC Lab's original server-side motivation without turning the repository into a service-maintenance burden. A small standard-library worker now translates stable JSON/NDJSON jobs into the v1 execution platform, returns deterministic results/snapshots, and adds filesystem/time containment suitable for subprocess, SSH, CI, and container deployments.

## v1.2.0 — Parallel Server Orchestration — 2026-08-27

v1.2 moved PPC Lab's server use from individual transport-neutral jobs to durable large-run orchestration while deliberately avoiding a permanent service stack. A standard-library scheduler now runs stable worker jobs concurrently, fingerprints inputs by content, caches successful deterministic evidence, resumes interrupted result directories, and preserves filesystem containment before both hashing and execution. The worker protocol remains the execution boundary; orchestration is a replaceable layer above it.
## v1.3.0 — Distributed Worker Fleet — 2026-08-27

v1.3 extended the stable server-side stack across multiple machines while preserving the low-maintenance design. A standard-library controller now negotiates installed host capabilities, stages target bytes by SHA-256 over local/OpenSSH transports, bounds concurrency per host, filters placement by tags/backend support, and retries transient infrastructure failures without retrying ordinary deterministic guest failures. The job/worker protocol remains unchanged; the fleet is an outer deployment layer rather than a new execution API.

## v1.4.0 — Evidence Server & Result Index — 2026-08-28

v1.4 made fleet/orchestration output durable without adding a server daemon. PPC Lab now has a standard-library evidence tool that canonicalizes and content-addresses PPC Lab JSON, records every original source/raw hash, indexes execution/provenance fields in a local SQLite database, and verifies the object store by hash. Orchestration and fleet runs can publish directly into the store. The evidence boundary intentionally records target-input hashes rather than silently copying proprietary binary bytes.

## v1.5.0 — Research API Service — 2026-08-28

v1.5 added an optional dependency-free HTTP transport after the server/fleet/evidence stack made a persistent integration endpoint worthwhile. The API deliberately wraps rather than replaces the stable worker contract, defaults to loopback, requires bearer authentication for remote binds, preserves worker containment, and keeps the evidence network surface read-only. TLS and public-facing service concerns remain deployment infrastructure rather than PPC Lab core responsibilities.


## v1.6.0 — Trace Intelligence & Coverage Analytics — 2026-08-28

v1.6 promoted instruction traces into reusable behavioral-analysis artifacts: dynamic coverage/hotness, observed CFG/calls, A/B trace comparison, Graphviz export, evidence-store persistence, and decompiler-evidence enrichment while keeping `ppc-lab-trace-v1` compatible.

## v1.8.0 — Automated Differential Triage — 2026-08-28

PPC Lab gained an automated triage layer above the stable trace and worker protocols. Two existing traces or two live engine/backend runs can be aligned to locate the first behavioral divergence, later resynchronization, and architectural snapshot differences. The resulting bundle is intentionally evidence-only and can carry a bounded `repro.job.json` without copying proprietary target bytes.

## v1.7.0 — Behavioral Corpus & Replay — 2026-08-28

v1.7 converted deterministic experiments into a first-class long-lived regression corpus, with SHA-256-pinned external inputs, backend-neutral behavioral expectations, replay/bless/minimize workflows, and explicit-only fixture embedding.

## v1.9.0 — Guided Exploration & Corpus Synthesis — 2026-08-28

v1.9 added a deterministic exploration layer above the stable worker protocol. Explicit register, write, binding, and syscall-return domains can be explored either exhaustively for small spaces or through a novelty-guided breadth-first frontier. Dynamic PC coverage and backend-neutral architectural outcome fingerprints decide which cases remain interesting, and successful novel cases can be promoted directly into the behavioral corpus while target binaries remain external and SHA-256-pinned.
## v2.0.0 — Autonomous Research Campaigns — 2026-08-28

v2.0 closed the loop between the v1.x research primitives without bloating the C++ execution core. `ppc-lab-campaign` now treats exploration, corpus replay, differential triage, and evidence publication as checkpointed stages under one manifest/hash/root/budget contract. Successful novel cases can flow directly into durable regressions; selected findings can flow into standard triage bundles; all resulting PPC Lab JSON can flow into the evidence index. Resume is deliberately exact—changing the campaign manifest or PPC Lab engine version requires a new run directory—and private target bytes remain external by default.

