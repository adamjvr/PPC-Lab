# Mach-O PowerPC intake

PPC Lab v0.3 directly inspects, maps, relocates, disassembles, and executes
**32-bit big-endian PowerPC Mach-O** images.

## Containers

- thin `MH_MAGIC` PowerPC images;
- fat `FAT_MAGIC` containers when a 32-bit PowerPC slice is present.

The loader intentionally targets classic 32-bit PPC Mach-O, not PPC64 or
little-endian Mach-O.

## File types

| Type | Mapping policy |
|---|---|
| `MH_EXECUTE` | Keeps declared segment VM addresses. |
| `MH_BUNDLE` | Keeps declared segment VM addresses. |
| `MH_DYLIB` | Rebases the first mapped segment to `--image-base`. |
| `MH_OBJECT` | Lays out sections deterministically from `--image-base`. |

`LC_SEGMENT` sections and permissions are parsed. `LC_SYMTAB` symbols are
exposed through the common symbol model.

## Entry discovery

PPC Lab tries, in order supported by available metadata:

- PPC thread-state program counter from `LC_THREAD` / `LC_UNIXTHREAD`;
- `LC_MAIN` entry file offset translated through its containing segment;
- conventional symbols such as `_main`, `_start`, `main`, and `start`;
- first `__text` region for relocatable object-style research when necessary.

You can always override discovery with `--entry` or `--entry-symbol`.

## Relocations

v0.3 supports common **non-scattered** PowerPC Mach-O relocation forms used by
ordinary static/object code paths, including:

- vanilla 32-bit relocation;
- BR24 and BR14 branch relocation;
- HI16, LO16, HA16, and LO14 paired relocation using `PPC_RELOC_PAIR`.

Scattered relocations, section-difference families, or other unsupported
relocation semantics fail explicitly. Add them only with a target plus a
synthetic regression proving the exact behavior.

## CLI

```bash
ppc-lab macho-info app
ppc-lab image-info app
ppc-lab symbols app
ppc-lab disasm --macho app --count 64
ppc-lab call --macho app --backend builtin
```

For a dylib/object that needs rebasing/import binding:

```bash
ppc-lab call --macho module \
  --image-base 0x13000000 \
  --entry-symbol _process \
  --bind _memcpy=0x30000100
```

## Runtime boundary

Mach-O intake is a file loader, not an early-Mac-OS-X emulator. Mach traps,
Carbon/Cocoa services, dyld behavior, libc, pthreads, syscalls, Objective-C
runtime state, and other host services must be stubbed/profiled when a target
actually reaches them.
