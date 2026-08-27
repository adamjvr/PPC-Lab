# PPC Lab roadmap

This is a **capability roadmap, not a schedule**. PPC Lab is infrastructure: ship
large useful chunks, then leave it alone until a real PPC target exposes the
next missing capability.

## Current: v0.4 — Research Machine — COMPLETE

v0.4 turns the v0.3 binary-intake engine into a repeatable behavioral-research
workflow:

- reusable minimal runtime personalities for Classic Mac and libc/POSIX leaf
  services;
- automatic imported-symbol binding to deterministic runtime stubs;
- symbol-aware execution traces;
- `ppc-lab-metadata-v1` machine-readable normalized intake metadata;
- `ppc-lab-snapshot-v1` deterministic CPU/memory/symbol snapshots;
- snapshot comparison and first-class differential execution;
- JSON batch experiment manifests and parameter sweeps;
- machine-readable trace capture and decompiler-neutral evidence packages;
- thin Ghidra, IDAPython, and Binary Ninja evidence import helpers.

**Exit condition achieved:** a researcher can choose a routine, define a
repeatable experiment, execute it, preserve state/trace evidence, compare runs,
and push normalized evidence back into a decompiler without rebuilding an ad
hoc glue stack for every target.

## v0.5 — PPC Coverage Monster

One concentrated execution-hardening milestone:

- aggressively fill PPC32 instruction gaps encountered by real workloads;
- improve CR/XER/FPSCR/SPR edge-case fidelity where validation demands it;
- structured exception, trap, and syscall interception;
- stronger builtin-vs-Unicorn backend parity tests;
- fuzz/property-style decoder/interpreter/memory/loader regressions;
- stress malformed binary intake and relocation streams;
- expand reusable ABI/runtime helpers only where actual workloads need them;
- PPC64 and little-endian scaffolding only if cheap or demanded by a live
  target.

**Exit condition:** ordinary PPC32 user-space routines should fail because of a
missing external environment far more often than because PPC Lab cannot execute
the instructions themselves.

## v1.0 — Useful general PPC research platform

> Throw a supported PPC binary at PPC Lab, inspect it, find an interesting
> routine, execute it in a controlled environment, trace/stub/bind what it
> touches, compare behavior, and feed the evidence back into decompilation.

v1.0 does not require emulating every PowerPC machine or operating system. It
requires a stable, documented, extensible research platform proven across
unrelated projects.

## Later, only when justified

Potential post-1.0 work: PPC64, little-endian PowerPC, deeper OS personalities,
JIT backends, remote workers, richer debugger protocols, and deeper decompiler
plugins. None are obligations.
