# PPC32 ISA coverage and fidelity

PPC Lab v0.5 targets **32-bit big-endian PowerPC user-space research**. It is not
trying to model a particular processor pipeline, MMU, cache hierarchy, or board.
The builtin backend implements architectural effects needed to execute isolated
routines deterministically.

## Broadly covered families

The builtin backend covers the ordinary 32-bit compiler-generated core used by
PPC Lab's tests and active research workloads, including:

- integer immediates, compares, rotate/mask, logical and shift operations;
- conditional/direct/indirect branches, LR/CTR, CR compare and CR logical forms;
- byte, halfword and word D-form and indexed loads/stores, including update forms;
- byte-reversed word/halfword loads and stores;
- carry/extend integer arithmetic and common OE overflow variants;
- low/high multiply and signed/unsigned divide forms;
- XER/LR/CTR SPR moves and `mcrxr`;
- `lwarx` / `stwcx.` deterministic reservation-pair behavior;
- common single/double floating-point arithmetic, compares, conversion, sign,
  reciprocal/square-root helper forms, and selected FPSCR/CR record behavior;
- `sync`, `eieio`, `isync`, common cache hint/flush instructions, `icbi`, and
  `dcbz` at the deterministic research-harness level;
- structured `sc`, `tw`, and `twi` boundaries.

This document intentionally describes **families**, not a frozen promise that
every PowerPC Book I opcode is implemented. Unsupported instructions stop with
`unsupported_instruction`; that visible stop is the extension point.

## Intentional approximations

Some instructions have hardware behavior that cannot be meaningful without a
machine model. PPC Lab documents the deterministic substitute instead of
pretending to emulate hardware it does not have:

- cache hint/flush/order instructions that do not alter architecturally visible
  harness memory are deterministic no-ops;
- `dcbz` zeros a deterministic aligned 32-byte block;
- `lwarx`/`stwcx.` use a single-threaded reservation address/valid bit; there is
  no coherence fabric or competing processor;
- reciprocal/square-root estimate instructions currently use deterministic host
  arithmetic rather than a model-specific estimate table;
- floating-point exception/sticky behavior is partial; v0.5 improves the record
  path needed by supported forms but is not a complete FPSCR exception model;
- PPC privileged state, MMU/TLB behavior, interrupts, decrementer, and processor-
  specific SPRs remain outside the user-space call harness.

When bit-exact processor-specific behavior matters, add a target validation
fixture and document the processor assumption rather than silently tightening a
generic approximation around one sample.

## Architecture boundary

Current first-class architecture: `PPC32 big-endian`.

PPC64 and little-endian PowerPC are deliberately deferred until a real target
needs them. They should not be introduced as partially functional mode flags that
make successful-looking results ambiguous.

## Adding coverage

When execution stops on a missing instruction:

1. confirm the encoding and semantics against an appropriate PowerPC reference;
2. implement the builtin architectural effect;
3. add readable disassembly;
4. add a minimal deterministic state vector;
5. include CR/XER/FPSCR/memory/reservation effects where relevant;
6. compare against Unicorn or another independent implementation when useful;
7. preserve the real target regression under its profile if redistribution
   permits it.
