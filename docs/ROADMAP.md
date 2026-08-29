# PPC Lab roadmap

This is a **capability roadmap, not a schedule**. PPC Lab is infrastructure: ship a large useful chunk when a real PPC target needs it, then leave the tool alone and return to the actual reverse-engineering project.

## v1.0 — General PPC research platform — COMPLETE

The original platform goal is met:

> Throw a supported PPC binary at PPC Lab, inspect it, find an interesting routine, execute it in a controlled environment, trace/stub/bind what it touches, compare behavior, and feed the evidence back into decompilation.

v1.0 includes native ELF32 PPC, Mach-O PPC32, and PEF/CFM intake; auto-detected `--image` execution; raw-image escape hatches; deterministic PPC32-BE execution; runtime/import boundaries; symbol-aware traces; snapshots/results/metadata; batch/differential tooling; decompiler evidence bridges; cross-platform CI; and an installed public C++ package.

## v1.1 — Server worker protocol — COMPLETE

The original "server-side harness" intent now has a stable, transport-neutral boundary: `ppc-lab-job-v1` jobs, `ppc-lab-worker-response-v1` responses, one-shot execution, resilient NDJSON streaming, filesystem containment, and wall-clock containment. This deliberately avoids turning PPC Lab into a web-service project.

## v1.2 — Parallel server orchestration — COMPLETE

The stable worker boundary can now be driven as server infrastructure without bespoke client glue: orchestration manifests, bounded parallel execution, atomic result directories, exact resume semantics, and deterministic content-addressed caching are provided without adding a daemon/database/cloud stack.

## v1.3 — Distributed worker fleet — COMPLETE

The stable worker boundary now scales across multiple installed hosts without a service stack: capability/version negotiation, OpenSSH/local transports, content-addressed target staging, host slots/tags/backend eligibility, retries/failover for transient infrastructure faults, central cache/resume, and atomic fleet evidence are included.

## v1.4 — Evidence server & result index — COMPLETE

Server/fleet output can now become durable research infrastructure instead of disposable result directories. A local content-addressed JSON object store plus SQLite index deduplicates evidence, preserves provenance, supports cross-run queries by target hash/execution metadata, verifies object integrity, and can be populated automatically by orchestration/fleet runs. Target binaries are deliberately not copied into the evidence store.

## v1.5 — Research API service — COMPLETE

The persistent network/service transport became justified for easier cross-project/server integration. A dependency-free optional HTTP layer now exposes health/capabilities, the stable v1 worker execution contract, and read-only evidence queries while retaining loopback-first binding, bearer authentication for remote binds, worker root/time containment, bounded bodies, and no embedded TLS/cloud stack.

## v1.6 — Trace intelligence & coverage analytics — COMPLETE

Instruction traces can now be promoted into durable behavioral evidence: dynamic coverage, hot functions/instructions, observed blocks/control flow/calls, Graphviz export, trace diffing, evidence-store ingestion, and decompiler-evidence enrichment.

## v1.7 — Behavioral corpus & replay — COMPLETE

Successful experiments can now become durable engine regressions instead of disappearing into result folders. Corpus cases pin every input by SHA-256, preserve stable behavioral expectations independently of backend labels/transport noise, replay against current PPC Lab builds, support external private inputs or explicit redistributable embedding, and provide deliberate bless/minimize workflows.

## v1.8 — Automated differential triage — COMPLETE

Backend/engine disagreements can now be converted automatically into reviewable evidence: common-prefix detection, first divergence classification, trace resynchronization, snapshot-state comparison, dual-worker execution, input provenance hashing, and reduced instruction-budget repro bundles. Target binaries remain external.

## v1.9 — Guided exploration & corpus synthesis — COMPLETE

Explicit PPC call-input domains can now be explored deterministically rather than by blind fuzzing. Guided BFS expands only coverage- or behavior-novel cases, small domains can use bounded Cartesian enumeration, target inputs are SHA-256-pinned under the existing root-safety model, and successful novel executions can be promoted directly into the behavioral corpus without copying private binaries.

## v2.0 — Autonomous research campaigns — COMPLETE

The individual v1.x research primitives now compose into a bounded checkpointed lifecycle. A campaign can validate target/root/tool capability conditions, run deterministic guided exploration, promote successful novel cases into the behavioral corpus, replay/verify those durable expectations, automatically triage selected findings across engine/backend configurations, publish the resulting JSON evidence, and resume an interrupted run only when the exact campaign manifest and engine version still match. This remains a standard-library orchestration layer rather than a second execution engine or a permanent service requirement.

## v2.1 — Campaign intelligence & prioritization — COMPLETE

Campaign execution is now yield-aware without becoming nondeterministic. Adaptive exploration can favor high-yield mutation axes and stop on a configured novelty plateau; a separate deterministic priority report ranks completed cases, quantifies axis/value yield, and drives campaign triage ordering. The hard case/wall/triage budgets remain authoritative, and all ranking inputs/weights are recorded for replay.

## v2.2 — Campaign scheduling & resource governance — COMPLETE

Autonomous campaigns can share long-lived research hosts under deterministic weighted fair-share, within-project priority, global/per-project concurrency limits, case-admission quotas, wall accounting, exact resume, graceful drain, and cancellation policy. The scheduler remains a local process layer above campaigns rather than a permanent queue/database requirement.

## v2.3 — Campaign control plane — COMPLETE

Scheduler runs can now live in a persistent priority queue with foreground supervision, live process/scheduler telemetry, pause/resume/drain/cancel controls, restart-aware recovery, single-supervisor coordination, and append-only run history. The control plane deliberately stays filesystem-backed and dependency-free.

## v2.4 — Research knowledge graph — COMPLETE

Accumulated research is now relationship memory rather than disconnected result directories. A dependency-free SQLite graph connects target SHA-256 identities, JSON evidence, symbols/functions/addresses, dynamic coverage, stable behavior fingerprints, corpus cases, triage findings, campaigns, and decompiler annotations. Existing evidence stores can be synchronized, graph neighborhoods/paths can explain cross-project relationships, and target-scoped knowledge exports back into the neutral decompiler-evidence format without copying private binaries.

## v2.5 — Automated hypothesis engine — COMPLETE

Accumulated execution evidence can now generate bounded, inspectable research hypotheses. PPC Lab infers candidate argument/state roles with transparent metrics, emits ordinary follow-up exploration manifests, content-pins supporting cases, requires verified execution evidence for explicit promotion, and connects candidate/supported hypotheses into the knowledge graph. The implementation is deterministic and standard-library-only; it does not introduce an opaque AI dependency.

## v3.0 — Mature PPC research automation platform — COMPLETE

The mature-platform release consolidates documentation/operational contracts, adds a release-level end-to-end acceptance scenario spanning intake through hypothesis promotion, hardens migration/upgrade checks for persisted evidence/knowledge/control data, and freezes the long-term maintenance boundary. No new execution subsystem was added merely to inflate v3.0; ISA/runtime/backend expansion remains demand-driven by real PPC targets.

## Post-2.0 — only when justified

Potential future capability buckets:

- PPC64 and/or little-endian PowerPC when an actual target requires them;
- deeper Classic Mac, POSIX, console, firmware, or other runtime personalities;
- additional loader relocation families exposed by real binaries;
- richer debugger protocols, asynchronous queues, or service transports beyond the intentionally small v1.5 HTTP boundary when a real deployment requires them;
- JIT/alternate execution backends;
- deeper Ghidra/IDA/Binary Ninja plugins;
- additional ISA fidelity where a real workload exposes a missing/approximate instruction.

None of these are standing obligations. A missing capability should arrive with a real target, a minimal reproduction, and a regression test.

## Post-roadmap LTS checkpoint: v3.1

v3.1 does not reopen the standing feature roadmap. It formalizes the target-adapter and release-engineering contracts needed to keep the completed v3 platform inexpensive to maintain. Further work remains target-driven.

## Post-roadmap LTS checkpoint: v3.2

v3.2 adds compatibility and upgrade assurance only. The standing feature roadmap remains complete; further execution/runtime expansion is still target-driven.

## Post-roadmap LTS checkpoint: v3.7

v3.7 adds observability and capacity planning only. It measures the mature server/control-plane stack through stable JSON contracts and keeps the standing execution/runtime roadmap frozen. New PPC ISA/runtime features remain target-driven.
## Post-roadmap LTS checkpoint: v3.9

v3.9 adds content-addressed offline replication and multi-site resilience only. Evidence and knowledge can converge across independent research servers while active control queues remain site-local. The standing PPC execution/runtime roadmap remains frozen and target-driven.
## Post-roadmap LTS checkpoint: v3.9.2

v3.9.2 adds portable release qualification only. It converts the existing manifest/build/test/install gates into one CI-provider-neutral command and machine-readable report after a real hosted-runner failure demonstrated that release evidence must be separable from CI transport availability. The standing PPC execution/runtime roadmap remains frozen and target-driven.

