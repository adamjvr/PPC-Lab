# Extraction history

PPC Lab v0.1.0 was extracted from the working `X0X-ReAnimated_2026-08-22_PPC_Harness_Phase1` milestone rather than rewritten from scratch.

The original harness had already demonstrated genuine external PowerPC execution: the relocated ReBirth Distortion constructor at `0x10000cf4` returned normally after 133,027 instructions under the dependency-free interpreter, and the first 128 object bytes produced FNV-1a64 `0x418c9e14a76a422e`.

During extraction:

- `x0x::ppc` became `ppclab::ppc`;
- the executable became `ppc-lab`;
- build options and result schemas were renamed;
- target-specific import addresses were removed from the core;
- import behaviors became address bindings supplied at invocation time;
- ReBirth addresses and validation moved to `profiles/rebirth/`;
- generic heap/stack/import/return address controls were exposed by the CLI;
- the previous synthetic and differential-result tests were retained and generalized.


## 0.1.1 licensing/documentation hardening — 2026-08-26

PPC Lab was explicitly published as free software under GNU GPL version 3.0 only (`GPL-3.0-only`). The repository gained the canonical GPLv3 license text, SPDX identifiers on source/build/script files, contributor guidance, and expanded quick-start, CLI, development, result-format, profile, architecture, and research-workflow documentation.

## v0.2.0 — first generic executable loader

The first post-extraction capability milestone added reusable ELF32 PowerPC
intake rather than another target-specific adapter. PPC Lab can now inspect,
disassemble, map, and execute fixed-address big-endian `EM_PPC` `ET_EXEC`
images directly. Synthetic ELF tests prove segment permissions, BSS zero-fill,
entry-point selection, CLI inspection/disassembly, and actual execution through
the normal call harness. Raw and Classic CFM workflows remain intact.
