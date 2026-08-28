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

## Post-1.4 — only when justified

Potential future capability buckets:

- PPC64 and/or little-endian PowerPC when an actual target requires them;
- deeper Classic Mac, POSIX, console, firmware, or other runtime personalities;
- additional loader relocation families exposed by real binaries;
- richer debugger protocols or a persistent network/service transport **only if** a deployment cannot use the v1.1 worker plus v1.3 OpenSSH fleet infrastructure;
- JIT/alternate execution backends;
- deeper Ghidra/IDA/Binary Ninja plugins;
- additional ISA fidelity where a real workload exposes a missing/approximate instruction.

None of these are standing obligations. A missing capability should arrive with a real target, a minimal reproduction, and a regression test.
