# Original PPC Distortion Constructor — External First Contact

**Date:** 2026-08-22
**Payload policy:** metadata/hashes only; no original executable bytes are stored in this validation record.

The canonical user-owned ReBirth 2.0.1 StuffIt specimen was regenerated through the complete clean-room reference chain:

```text
StuffIt method-13 forks
        ↓
Disk Copy NDIF
        ↓
raw HFS
        ↓
targeted VISE catalog extraction
        ↓
ReBirth Engine PEF
        ↓
3,972 PEF relocations
        ↓
external relocated CODE / DATA
```

Every known intermediate/final SHA-256 matched the previously recovered canonical values.

The server-side built-in PPC32 big-endian backend then invoked:

```text
entry  0x10000cf4  Distortion constructor
r2     0x20008000  recovered TOC
r3     0x40010000  deterministic harness object
```

Result:

```text
stop              returned
instructions       133,027
object bytes hashed 128
object FNV-1a64     0x418c9e14a76a422e
```

During discovery, the harness first exposed the CFM `BlockMoveData` import at synthetic identity `0x300001c8`. After an exact byte-copy stub was added, the constructor exposed `divwu`, `subfic`, indexed floating-point forms, and MathLib `sin`; those demanded ISA forms are now covered by built-in microtests.

`BlockMoveData` is modeled exactly for the harness memory contract. Transcendental MathLib functions currently use host `libm` only as **execution aids**. Therefore this result proves that the original PPC constructor can execute to completion under the server harness, but it does not yet claim bit-exact equivalence to Classic Mac MathLib transcendental rounding.

The external regression can be repeated with:

```bash
./Tools/verify-ppc-reference.command \
  /path/to/rebirth_rb-338_2_0_1_cd.sit \
  /tmp/x0x-ppc-reference
```
