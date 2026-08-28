# PPC Lab roadmap

This is a **capability roadmap, not a schedule**. PPC Lab is infrastructure: ship
large useful chunks, then leave it alone until a real PPC target exposes the
next missing capability.

## Current: v0.5 — PPC Coverage Monster — COMPLETE

v0.5 concentrates on execution hardening rather than adding another container
format:

- materially broader PPC32 integer, CR, load/store, atomic, byte-reverse,
  cache/order, arithmetic-overflow, and floating-point execution coverage;
- structured `sc`, `tw`, and `twi` interception;
- deterministic syscall-return bindings and explicit trap-ignore policy;
- stronger CR/XER/FPSCR behavior around newly supported instructions;
- builtin-vs-Unicorn parity regression when Unicorn is available;
- deterministic interpreter/disassembler/memory property tests;
- malformed ELF/Mach-O/PEF intake stress tests.

**Exit condition achieved for the milestone:** PPC Lab now covers a substantially
larger body of ordinary PPC32 compiler output while keeping unknown OS/runtime
behavior visible rather than pretending to emulate it. New opcode work remains
demand-driven: a real unsupported instruction should arrive with a regression.

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
