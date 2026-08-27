# ELF32 PowerPC intake

PPC Lab v0.3 accepts **32-bit, big-endian, `EM_PPC` ELF** and deliberately
rejects ELF64, little-endian ELF, and non-PowerPC machine types.

## Accepted ELF types

| ELF type | v0.3 behavior |
|---|---|
| `ET_EXEC` | Maps `PT_LOAD` segments at their original virtual addresses. |
| `ET_DYN` | Rebases loadable image at `--image-base` and applies supported relocations. |
| `ET_REL` | Lays out allocatable sections from `--image-base`, resolves symbols, applies supported section relocations. |

For segments, file bytes are copied, `p_memsz - p_filesz` is zero-filled, and
memory permissions are derived from `PF_R/PF_W/PF_X`.

For relocatable objects, `SHF_ALLOC` sections are laid out deterministically
while honoring section alignment. `SHT_NOBITS` is zero-filled.

## Metadata and symbols

```bash
ppc-lab elf-info target.elf
ppc-lab image-info target.elf
ppc-lab symbols target.elf
```

PPC Lab parses section metadata and `SHT_SYMTAB`/`SHT_DYNSYM` where present.
Defined symbols are translated to runtime addresses after rebasing/layout.
Undefined symbols used by relocations must be resolved with `--bind`, except
weak unresolved symbols which may resolve to zero.

## Entry behavior

- `ET_EXEC`/`ET_DYN`: `e_entry`, adjusted by load bias where appropriate;
- `ET_REL`: normally use `--entry-symbol NAME` or `--entry ADDRESS` because
  relocatable objects do not have a normal process entry point.

Example:

```bash
ppc-lab call --elf module.o \
  --image-base 0x12000000 \
  --entry-symbol render \
  --set r3=0x40010000
```

## Supported common PPC relocation families

v0.3 implements the static/research-oriented relocation subset currently needed
by our fixtures and expected near-term targets, including:

```text
R_PPC_NONE
R_PPC_ADDR32 / R_PPC_UADDR32
R_PPC_ADDR16 / R_PPC_UADDR16
R_PPC_ADDR16_LO / HI / HA
R_PPC_ADDR24
R_PPC_ADDR14 and branch-prediction variants
R_PPC_REL24 / R_PPC_PLTREL24 / R_PPC_LOCAL24PC
R_PPC_REL14 and branch-prediction variants
R_PPC_REL32 / R_PPC_PLTREL32
R_PPC_GLOB_DAT / R_PPC_JMP_SLOT / R_PPC_PLT32
R_PPC_RELATIVE
R_PPC_SECTOFF / LO / HI / HA
```

`SHT_REL` and `SHT_RELA` are parsed. `R_PPC_COPY` and unknown/unsupported
relocation semantics are rejected explicitly rather than approximated.

## What this does not imply

Loading an ELF does **not** emulate a Linux/POSIX runtime or a dynamic linker.
GOT/PLT-heavy images, TLS, syscalls, libc dependencies, unusual ABI startup
state, or relocation types outside the implemented subset may require a future
runtime personality or loader extension.
