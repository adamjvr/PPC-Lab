# PPC Lab roadmap

This is a **capability roadmap, not a schedule**. PPC Lab is infrastructure. We
ship large useful chunks, then stop working on it until an actual PPC target
needs the next chunk.

## Current: v0.3 — Binary Intake Blitz — COMPLETE

The binary-intake layer is now broad enough that most near-term PPC research can
start from the original container instead of a hand-relocated blob:

- PEF/CFM parsing, instantiation, imports/exports, entry discovery, pidata, and
  standard relocation bytecode;
- thin/fat PPC32 big-endian Mach-O for objects/executables/dylibs/bundles;
- ELF32 big-endian `ET_EXEC`, `ET_DYN`, and `ET_REL`;
- native symbols and common PPC relocation handling;
- `image-info`, `symbols`, cross-format `disasm`, and cross-format `call`;
- `--image-base`, `--entry-symbol`, and explicit `--bind` import resolution;
- synthetic execution regressions for all native loader families.

## v0.4 — Research Machine

Condense the analysis/integration work into one serious milestone:

- reusable runtime personalities, beginning with whichever target needs one
  first (Classic Mac services and/or libc/POSIX);
- symbolized execution traces and call/import reporting;
- batch experiment runner for parameter sweeps and reproducible fixtures;
- snapshot/state capture and deterministic state comparison;
- first-class differential execution workflows;
- Ghidra integration helpers, with IDA/Binary Ninja adapters where cheap;
- machine-readable intake metadata suitable for external decompiler tooling;
- profile-level symbol maps and reusable runtime bindings.

**Exit condition:** a researcher can select a function in a decompiler, prepare
a repeatable experiment, execute it through PPC Lab, and consume symbolized
behavioral evidence without hand-gluing every step.

## v0.5 — PPC Coverage Monster

One concentrated execution-hardening milestone:

- aggressively fill PPC32 instruction gaps encountered by real workloads;
- improve CR/XER/FPSCR/SPR edge-case fidelity where validation demands it;
- structured exception/trap/syscall interception;
- stronger builtin-vs-Unicorn backend parity tests;
- fuzz/property-style decoder/interpreter/memory/loader regressions;
- stress malformed binary intake and relocation streams;
- expand reusable ABI/runtime helpers;
- PPC64 and little-endian scaffolding only if doing so is cheap or a live target
  demands it.

**Exit condition:** ordinary PPC32 user-space routines should fail because of a
missing external environment far more often than because PPC Lab cannot execute
the instructions themselves.

## v1.0 — Useful general PPC research platform

The practical v1.0 definition is intentionally simple:

> Throw a supported PPC binary at PPC Lab, inspect it, find an interesting
> routine, execute it in a controlled environment, trace/stub/bind what it
> touches, compare behavior, and feed the evidence back into decompilation.

v1.0 does **not** require emulating every PowerPC machine or operating system.
It requires a stable, documented, extensible research platform that has proven
itself across unrelated projects.

## Later, only when justified

Potential post-1.0 work includes PPC64, little-endian PowerPC, more OS/runtime
personalities, JIT backends, remote execution workers, richer debugger
protocols, and deeper decompiler plugins. None of these are obligations.
