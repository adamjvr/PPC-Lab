# PEF / CFM PowerPC intake

v0.3 adds native **PowerPC PEF/CFM** intake so Classic Mac research no longer
requires every project to pre-extract and relocate raw sections by hand.

The loader recognizes the PEF container signatures `Joy!` / `peff` and PowerPC
architecture tag `pwpc`.

## Section instantiation

PPC Lab parses PEF section headers and deterministically instantiates reusable
runtime sections from `--image-base`, respecting each section's alignment.
Supported instantiated section kinds include code, unpacked data,
pattern-initialized data, constant data, and executable data. The loader section
is parsed as metadata rather than mapped as target program memory.

## Pattern-initialized data

PEF packed/pattern data is expanded by the loader, including the standard
zero-fill, block-copy, repeated-block, interleave, and custom-block command
families with PEF variable-length counts. Invalid/truncated streams fail.

## Imports and exports

The PEF loader parses:

- imported-library/symbol metadata;
- weak-import state;
- export hash/table metadata;
- exported symbol names/locations;
- main, initialization, and termination entry descriptors.

Unresolved strong imports needed by relocation must be supplied explicitly with
`--bind NAME=ADDRESS`. Weak imports can resolve to zero where permitted.

## Relocation bytecode

PEF does not use a flat array of ELF-style relocations. Its loader section
contains compressed relocation instruction streams. PPC Lab v0.3 executes the
standard relocation families needed for general CFM intake, including:

- section-C / section-D run relocations and skip forms;
- transition-vector and vtable run forms;
- import-run forms;
- small set-section / by-section / by-import forms;
- relocation-position increments and explicit position setting;
- small and large repeat forms;
- large by-import and set/by-section forms.

Reserved/third-party opcodes and malformed/nested-repeat behavior outside the
implemented contract are rejected visibly.

## Entry behavior

After relocation PPC Lab derives runtime addresses for PEF main/init/term
records. The main record becomes the default call entry. For CFM routines whose
entry is a transition vector, the existing explicit `--transition-vector`
calling path remains available.

## CLI

```bash
ppc-lab pef-info application.pef
ppc-lab image-info application.pef
ppc-lab symbols application.pef
ppc-lab disasm --pef application.pef --image-base 0x11000000 --count 64
ppc-lab call --pef application.pef --image-base 0x11000000 --backend builtin
```

External CFM imports remain target/runtime policy:

```bash
ppc-lab call --pef application.pef \
  --bind BlockMoveData=0x30000100 \
  --stub blockmove@0x30000100
```

## Boundary

PEF/CFM intake does not emulate the Classic Mac OS Toolbox, Mixed Mode Manager,
Code Fragment Manager process environment, resource manager, filesystem, or UI
runtime. It gets the container into deterministic PPC Lab memory correctly;
profiles/runtime personalities supply the environment needed by whichever
routine is being researched.
