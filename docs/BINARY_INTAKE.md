# Binary intake architecture

PPC Lab v1 exposes its native loaders through a shared `UniversalImageLoader`
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

The v1 CLI accepts exactly one primary input per call/disassembly. The preferred native-image form is:

```text
--image FILE    auto-detect ELF32 PPC, Mach-O PPC32, or PEF/CFM
```

Explicit selectors remain supported for scripts that want to assert the format:

```text
--code FILE     raw relocated PPC bytes
--elf FILE      ELF32 big-endian EM_PPC
--macho FILE    32-bit big-endian PowerPC Mach-O, thin or fat
--pef FILE      PowerPC PEF/CFM
```

`analyze FILE`, `image-info FILE`, and `symbols FILE` use the same format detection boundary as `--image`, preventing CLI and core detection rules from drifting apart.

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
UniversalImageLoader::detectFile / inspectFile / loadFile
Elf32Loader::inspectFile / loadFile
MachOLoader::inspectFile / loadFile
PefLoader::inspectFile / loadFile
```

`UniversalImageLoader` is the format-neutral v1 boundary. Format-specific loaders remain public for tooling that needs container-specific metadata. All loaders publish target-independent symbol state through the shared `ImageSymbol`/`SymbolBinding` model.
