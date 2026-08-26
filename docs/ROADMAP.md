# PPC Lab demand-driven roadmap

PPC Lab is infrastructure, not a product treadmill. This roadmap records the
next reusable capability classes so future work does not require reconstructing
intent from old chats. It is **not** a promise to implement features in order or
on a schedule.

## Completed foundation

### v0.1.x — deterministic call harness

- dependency-free PPC32-BE interpreter;
- optional Unicorn backend;
- deterministic raw code/data/heap/stack/import maps;
- direct calls and CFM transition vectors;
- target-bound import stubs;
- tracing, dumps, JSON results, differential tools;
- external target profiles;
- GPL-3.0-only repository and invariant CI.

### v0.2.0 — executable-image intake

- dependency-free ELF32 big-endian `EM_PPC` `ET_EXEC` loader;
- `PT_LOAD` mapping with permissions and BSS zero-fill;
- ELF entry-point execution through the normal `CallHarness`;
- `elf-info` inspection command;
- lightweight `disasm` command for raw or ELF code;
- synthetic loader + CLI execution regressions.

## Next capability buckets

Implement the first bucket demanded by an active reverse-engineering target.
Do not work through this list merely for completeness.

### Classic Mac intake

Promote reusable PEF/CFM parsing and relocation into PPC Lab when another
Classic Mac target needs it. Preserve transition-vector/TOC behavior already in
the call harness. Keep Toolbox/OS services as explicit runtime personality or
profile behavior rather than hard-coded assumptions.

### Symbol-aware research

Add generic symbol import/export when it removes repeated manual address work:
ELF symbol tables first if an active ELF target needs them, followed by PEF or
Mach-O symbols as justified. Symbols should annotate results/traces without
becoming required for execution.

### Mach-O PowerPC loader

Add fixed-address 32-bit PPC Mach-O intake for early Mac OS X research when a
real target arrives. Relocation/dyld behavior should remain explicit rather
than partially emulated.

### ELF relocations / ET_REL / ET_DYN

Add only the relocation families observed in real PPC objects/firmware. Reject
unknown relocation types. Do not quietly pretend a shared object is already
relocated.

### Better runtime personalities

Reusable personalities may model narrow ABI/runtime services such as libc-like
memory/string helpers, selected POSIX calls, or Classic Mac services. Keep
address bindings and target-specific semantics outside the CPU core.

### Analysis integration

Potential low-friction bridges:

- Ghidra export/import scripts;
- IDA/Binary Ninja address/symbol adapters;
- batch function-call experiment manifests;
- trace-to-symbol annotation;
- coverage summaries;
- compare PPC Lab state against native clean-room implementations.

### ISA expansion

Continue the existing rule: unsupported opcode from a real target -> implement
smallest correct reusable semantics -> synthetic regression -> resume target.
Full ISA coverage is not a goal by itself.

### PPC64 or little-endian PPC

These are separate architecture milestones. Do not complicate the PPC32-BE
baseline until an actual project needs them.

## Maintenance rule

A PPC Lab change should normally satisfy at least one of these tests:

1. it unblocks an active PPC reverse-engineering target;
2. it removes duplicated infrastructure from multiple profiles;
3. it improves reproducibility or catches a silent correctness failure;
4. it makes an already-supported capability materially easier to use.

If none apply, the feature can wait.
