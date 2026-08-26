# ReBirth profile

This is a **target profile**, not part of the PPC Lab execution core. It preserves the first real workload used to prove the original harness: a relocated, user-supplied ReBirth RB-338 2.0.1 PowerPC engine.

No commercial code, data, samples, songs, or UI resources are stored here. Only derived addresses, expected fingerprints, scripts, and historical validation records are committed.

## Distortion constructor regression

With externally prepared relocated sections:

```bash
export PPC_LAB_REBIRTH_CODE=/absolute/path/ReBirth_Engine.sec0.reloc.bin
export PPC_LAB_REBIRTH_DATA=/absolute/path/ReBirth_Engine.sec1.reloc.bin
export PPC_LAB_REBIRTH_LAYOUT=/absolute/path/ReBirth_Engine.reloc.json   # optional
./profiles/rebirth/scripts/distortion_ctor.sh
```

Known 2026-08-22 baseline using the built-in PPC32-BE backend:

- entry: `0x10000cf4`
- TOC/r2: `0x20008000`
- object/r3: `0x40010000`
- instructions: `133027`
- first 128 object bytes FNV-1a64: `0x418c9e14a76a422e`

The profile binds the few imported runtime calls needed by that path at invocation time. Those addresses do **not** exist in the generic PPC Lab core.


## Licensing and external bytes

The scripts, derived metadata, and validation records committed in this profile are distributed as part of PPC Lab under `GPL-3.0-only`. The original ReBirth executable/engine bytes are **not** included and must remain external researcher-supplied inputs.
