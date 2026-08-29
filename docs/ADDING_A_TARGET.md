# Adding a target profile

Since v3.1, start with the installed target SDK rather than hand-creating the profile skeleton:

```bash
ppc-lab-target init profiles/my-target --id my-target --name "My Target"
ppc-lab-target validate profiles/my-target
```

The generated `profile.json` is the stable `ppc-lab-target-profile-v1` contract. Existing hand-authored profile directories remain valid; adopting the manifest is recommended when they are next touched.

A profile is intentionally cheap. Most projects should need only a directory, a concise README, derived metadata, a deterministic invocation script, and validation records.

## Directory skeleton

```bash
mkdir -p profiles/my-target/{reference,scripts,validation}
```

Recommended layout:

```text
profiles/my-target/
├── README.md
├── reference/      derived addresses, symbols, hashes, layouts
├── scripts/        reproducible PPC Lab invocations
└── validation/     known-good results and research notes
```

## What belongs in a profile

Good profile material:

- product/firmware/version identification;
- executable section names and hashes;
- relocated section base addresses;
- entry points and transition-vector addresses;
- TOC/r2 values;
- known object/buffer addresses used by a fixture;
- imported-call address bindings;
- expected stop reason and instruction count;
- deterministic dump hashes;
- scripts and derived JSON metadata;
- notes explaining how evidence was obtained.

## What normally does not belong in a profile

Do not commit commercial/proprietary executable bytes, ROMs, samples, firmware, or other assets unless redistribution is clearly allowed.

PPC Lab's public profile should instead accept external paths. Prefer the original supported native container (ELF, Mach-O, or PEF) instead of creating unnecessary raw-section copies:

```bash
export PPC_LAB_TARGET=/absolute/path/target.bin
"$PPC_LAB_BIN" image-info "$PPC_LAB_TARGET"
"$PPC_LAB_BIN" call --pef "$PPC_LAB_TARGET" --image-base 0x11000000
```

If a target uses a custom/unsupported container or research already produced relocated sections, external raw paths remain valid:

```bash
export PPC_LAB_TARGET_CODE=/absolute/path/target.sec0.bin
export PPC_LAB_TARGET_DATA=/absolute/path/target.sec1.bin
./profiles/my-target/scripts/example.sh
```

## Minimal deterministic script

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${PPC_LAB_TARGET_CODE:?set PPC_LAB_TARGET_CODE}"
: "${PPC_LAB_TARGET_DATA:?set PPC_LAB_TARGET_DATA}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BIN="${PPC_LAB_BIN:-$ROOT/build/release/ppc-lab}"

"$BIN" call \
  --backend builtin \
  --code "$PPC_LAB_TARGET_CODE" \
  --data "$PPC_LAB_TARGET_DATA" \
  --entry 0x10001234 \
  --toc 0x20008000 \
  --set r3=0x40010000 \
  --stub blockmove@0x300001c8 \
  --max-instructions 250000 \
  --dump 0x40010000:128 \
  --json /tmp/my-target-result.json
```

A profile script should reduce a useful reverse-engineering question to one reproducible command.

## Record provenance

The profile README should answer:

- What exact target/version was analyzed?
- What external file(s) does the researcher need?
- How are the bytes extracted/relocated before PPC Lab sees them?
- Which addresses are original, relocated, inferred, or empirically verified?
- What result is considered the known baseline?
- Which parts are approximate, especially imported math/runtime behaviors?

## When the target stops

### Unknown import

Leave it trapped until its behavior is actually required. Once understood, add a generic core stub only if the behavior is reusable; keep the target address in the profile.

### Unsupported PPC instruction

Add that instruction to the built-in backend with a synthetic unit/microtest before retrying the target.

### Memory fault

First check relocation, data-map size, object pointers, TOC/globals, stack setup, and target-owned allocation assumptions.

## Promote repeated infrastructure

If multiple targets need the same runtime helper, or a file-format feature is inherently reusable, that is evidence it belongs in generic PPC Lab tooling. v0.3's ELF/Mach-O/PEF loaders are examples: file-format mechanics are generic, while target addresses, import policy, runtime services, and validation remain outside the core. Promotion should remove duplication without moving project-specific knowledge into generic code.

## Licensing

Profile scripts/metadata committed to this repository are GPL-3.0-only unless explicitly noted otherwise. External target binaries remain external inputs and are not distributed by PPC Lab.
