# ELF32 PowerPC support

PPC Lab v0.2.0 adds a dependency-free loader for fixed-address, 32-bit,
big-endian PowerPC ELF executables. The loader exists to remove repetitive
manual extraction work for embedded, bare-metal, and Unix-like PPC research
without turning PPC Lab into a full operating-system emulator or dynamic linker.

## Supported input contract

The current loader accepts an ELF file only when all of the following are true:

- ELF class is `ELFCLASS32`;
- byte order is `ELFDATA2MSB` (big-endian);
- machine is `EM_PPC` (`20`);
- ELF type is `ET_EXEC`;
- the file contains at least one non-empty `PT_LOAD` program segment;
- every load segment has `p_filesz <= p_memsz`;
- every file and virtual-memory range is in bounds.

The loader deliberately rejects `ET_REL`, `ET_DYN`, PPC64, and little-endian
ELF rather than guessing at relocation or ABI behavior that has not been
implemented.

## What mapping does

For each `PT_LOAD` segment PPC Lab:

1. maps `p_memsz` bytes at `p_vaddr`;
2. copies `p_filesz` bytes from `p_offset`;
3. leaves the remainder zero-filled, which provides normal BSS semantics;
4. derives read/write/execute permissions from `p_flags`;
5. records a deterministic mapping name such as `elf:PT_LOAD[0]`.

Executable mappings are internally readable because PPC Lab's instruction
fetch path reads the same backing byte store. This does not make a claim about
host or target MMU page-protection behavior.

`p_paddr`, alignment, and ELF flags are preserved as inspection metadata but do
not currently cause extra physical-memory/MMU behavior.

## Inspect without executing

```bash
./build/release/ppc-lab elf-info firmware.elf
```

Example output shape:

```text
PPC Lab ELF32 PowerPC image
file=firmware.elf
type=2 (ET_EXEC)
machine=20 (EM_PPC)
entry=0x00100000
flags=0x00000000
load_segments=2
  [0] R-X vaddr=0x00100000 ...
  [1] RW- vaddr=0x00200000 ...
```

Use this before execution to catch wrong architecture, endianness, executable
type, suspicious ranges, or an unexpected entry point.

## Disassemble loaded code

Start at the ELF `e_entry` value:

```bash
./build/release/ppc-lab disasm --elf firmware.elf --count 40
```

Start at another mapped executable address:

```bash
./build/release/ppc-lab disasm \
  --elf firmware.elf \
  --start 0x00101234 \
  --count 80
```

The disassembler intentionally shares PPC Lab's built-in instruction decoder.
It is a lightweight research view, not a replacement for Ghidra, IDA, Binary
Ninja, or a complete ISA disassembler. Unknown encodings remain visible as raw
`.long` values instead of being hidden.

## Execute an ELF image

The ELF entry point is used automatically:

```bash
./build/release/ppc-lab call \
  --elf firmware.elf \
  --backend builtin \
  --max-instructions 100000
```

Override the entry when calling an isolated function inside the image:

```bash
./build/release/ppc-lab call \
  --elf firmware.elf \
  --entry 0x00104560 \
  --set r3=0x40010000 \
  --set r4=64
```

A CFM transition vector may also override the entry when the mapped ELF image
is being used only as a convenient container for already-prepared target
memory. This is unusual but the call-harness precedence remains consistent:

1. `--transition-vector`, when supplied;
2. explicit `--entry`;
3. ELF `e_entry`.

## Auxiliary PPC Lab mappings

PPC Lab still creates its deterministic import, heap, and stack mappings around
an ELF call. If the ELF already occupies one of those address ranges, the call
fails with `invalid-configuration` rather than silently remapping target
memory. Move the harness-owned range explicitly, for example:

```bash
./build/release/ppc-lab call \
  --elf firmware.elf \
  --heap-base 0x50000000 \
  --stack-base 0x78000000
```

Unlike raw mode, ELF mode does **not** create the default synthetic data mapping
at `0x20000000`; writable ELF `PT_LOAD` segments are already the program's data
image. An additional external `--data FILE` can still be mapped explicitly when
a research fixture needs it.

## What is intentionally not implemented yet

PPC Lab v0.2.0 does not perform:

- section-header-based loading;
- symbol-table parsing;
- dynamic linking;
- ELF relocations;
- GOT/PLT construction;
- Linux process startup (`argc`, `argv`, `envp`, auxv);
- syscalls or an operating-system personality;
- MMU/TLB/physical-address simulation;
- PPC64 ELF.

Those features should be added only when a real research target requires them.
The current loader is intentionally small enough to audit and stable enough to
leave alone.
