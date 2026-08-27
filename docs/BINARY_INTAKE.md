# Binary intake architecture

v0.3 turns PPC Lab from a raw-section harness into a reusable PowerPC image
intake layer. ELF, Mach-O, and PEF use different file-format mechanics but feed
the same execution model.

## Common contract

Each native loader is responsible for four outputs:

1. **mapped memory** — code/data/BSS or instantiated sections with deterministic
   permissions and addresses;
2. **symbols** — reusable `ImageSymbol` records for defined/exported/imported
   names when the format exposes them;
3. **entry information** — a usable entry point when the format provides or
   allows PPC Lab to infer one;
4. **relocation results** — loader-time fixups applied before execution, with
   unsupported relocation semantics rejected explicitly.

`CallHarness` then adds the same heap, stack, return trampoline, register state,
runtime stub ranges, tracing, and deterministic outputs regardless of image
format.

## Format selection

The CLI accepts exactly one input per call/disassembly:

```text
--code FILE     raw relocated PPC bytes
--elf FILE      ELF32 big-endian EM_PPC
--macho FILE    32-bit big-endian PowerPC Mach-O, thin or fat
--pef FILE      PowerPC PEF/CFM
```

`image-info FILE` and `symbols FILE` auto-detect supported native containers by
magic. Execution still requires an explicit format switch so command lines are
self-documenting and deterministic.

## Address policy

`--image-base ADDRESS` supplies the deterministic allocation/rebase base for
formats that need one:

- ELF `ET_EXEC`: original fixed virtual addresses are retained;
- ELF `ET_DYN`: image is rebased from `--image-base`;
- ELF `ET_REL`: allocatable sections are laid out from `--image-base`;
- Mach-O `MH_EXECUTE`/`MH_BUNDLE`: VM addresses are retained;
- Mach-O `MH_DYLIB`: first mapped segment is rebased to `--image-base`;
- Mach-O `MH_OBJECT`: sections are laid out from `--image-base`;
- PEF: instantiated sections are deterministically laid out from
  `--image-base` while respecting section alignment.

The default base is `0x10000000`.

## Symbol binding policy

Unresolved imports are **not** guessed. Bind a target's external name to an
address explicitly:

```bash
ppc-lab call --elf object.o \
  --entry-symbol process \
  --bind memcpy=0x30000100 \
  --bind malloc=0x30000200
```

A binding establishes the address used by relocations. A behavioral stub is a
separate choice:

```bash
--bind memcpy=0x30000100 --stub blockmove@0x30000100
```

That separation is intentional. Loader/linking policy and runtime behavior are
different layers.

## Entry selection

For `call`, entry priority is:

1. CFM `--transition-vector` when explicitly requested;
2. explicit numeric `--entry`;
3. `--entry-symbol NAME` resolved from the loaded image;
4. loader-discovered/default native entry.

Raw code requires a numeric entry or transition vector. Native images may
provide their own entry.

## Why unsupported relocation types stop

A reverse-engineering harness must not produce convincing garbage. If PPC Lab
has not implemented the exact relocation semantics required by a file, loading
fails with a diagnostic. Add the missing relocation only when a real target
needs it and preserve a minimal synthetic fixture as a regression.

## C++ API

The public loader APIs are:

```text
Elf32Loader::inspectFile / loadFile
MachOLoader::inspectFile / loadFile
PefLoader::inspectFile / loadFile
```

All loaders publish target-independent metadata structures and use the shared
`ImageSymbol`/`SymbolBinding` model.
