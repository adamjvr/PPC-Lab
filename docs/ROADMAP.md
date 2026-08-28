# PPC Lab roadmap

This is a **capability roadmap, not a schedule**. PPC Lab is infrastructure: ship a large useful chunk when a real PPC target needs it, then leave the tool alone and return to the actual reverse-engineering project.

## v1.0 — General PPC research platform — COMPLETE

The original platform goal is met:

> Throw a supported PPC binary at PPC Lab, inspect it, find an interesting routine, execute it in a controlled environment, trace/stub/bind what it touches, compare behavior, and feed the evidence back into decompilation.

v1.0 includes native ELF32 PPC, Mach-O PPC32, and PEF/CFM intake; auto-detected `--image` execution; raw-image escape hatches; deterministic PPC32-BE execution; runtime/import boundaries; symbol-aware traces; snapshots/results/metadata; batch/differential tooling; decompiler evidence bridges; cross-platform CI; and an installed public C++ package.

## v1.1 — Server worker protocol — COMPLETE

The original "server-side harness" intent now has a stable, transport-neutral boundary: `ppc-lab-job-v1` jobs, `ppc-lab-worker-response-v1` responses, one-shot execution, resilient NDJSON streaming, filesystem containment, and wall-clock containment. This deliberately avoids turning PPC Lab into a web-service project.

## Post-1.1 — only when justified

Potential future capability buckets:

- PPC64 and/or little-endian PowerPC when an actual target requires them;
- deeper Classic Mac, POSIX, console, firmware, or other runtime personalities;
- additional loader relocation families exposed by real binaries;
- richer debugger protocols or a network/service transport **only if** a deployment cannot use the v1.1 JSON/NDJSON worker over subprocess/SSH/container infrastructure;
- JIT/alternate execution backends;
- deeper Ghidra/IDA/Binary Ninja plugins;
- additional ISA fidelity where a real workload exposes a missing/approximate instruction.

None of these are standing obligations. A missing capability should arrive with a real target, a minimal reproduction, and a regression test.
