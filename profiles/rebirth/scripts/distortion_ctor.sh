#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

: "${PPC_LAB_REBIRTH_CODE:?Set PPC_LAB_REBIRTH_CODE to the external relocated ReBirth Engine code section}"
: "${PPC_LAB_REBIRTH_DATA:?Set PPC_LAB_REBIRTH_DATA to the external relocated ReBirth Engine data section}"

BIN="${PPC_LAB_BIN:-$ROOT/build/release/ppc-lab}"
if [[ ! -x "$BIN" ]]; then
  "$ROOT/scripts/build.sh"
fi

REPORT="${PPC_LAB_REPORT:-/tmp/ppc-lab-rebirth-distortion-ctor.json}"
BACKEND="${PPC_LAB_BACKEND:-builtin}"

set +e
"$BIN" call \
  --backend "$BACKEND" \
  --code "$PPC_LAB_REBIRTH_CODE" \
  --data "$PPC_LAB_REBIRTH_DATA" \
  --entry 0x10000cf4 \
  --toc 0x20008000 \
  --set r3=0x40010000 \
  --max-instructions 200000 \
  --stub pow@0x30000000 \
  --stub cos@0x3000000c \
  --stub sqrt@0x30000010 \
  --stub sin@0x30000014 \
  --stub exp@0x30000018 \
  --stub blockmove@0x300001c8 \
  --dump 0x40010000:128 \
  --json "$REPORT"
rc=$?
set -e

echo "report=$REPORT"
if [[ -n "${PPC_LAB_REBIRTH_LAYOUT:-}" && -f "$PPC_LAB_REBIRTH_LAYOUT" ]]; then
  python3 "$ROOT/scripts/ppc_result_inspect.py" --result "$REPORT" --layout "$PPC_LAB_REBIRTH_LAYOUT"
else
  python3 "$ROOT/scripts/ppc_result_inspect.py" --result "$REPORT"
fi

if [[ $rc -eq 0 ]]; then
  python3 - "$REPORT" <<'PY'
import json, sys
p=sys.argv[1]
r=json.load(open(p))
expected_instructions=133027
expected_hash="0x418c9e14a76a422e"
actual_hash=(r.get("dumps") or [{}])[0].get("fnv1a64")
print(f"expected_instructions={expected_instructions}")
print(f"expected_object_fnv1a64={expected_hash}")
print(f"actual_instructions={r.get('instructions')}")
print(f"actual_object_fnv1a64={actual_hash}")
if r.get("instructions") != expected_instructions or actual_hash != expected_hash:
    raise SystemExit("WARNING: external regression result differs from the 2026-08-22 baseline")
print("ReBirth Distortion constructor regression PASS")
PY
fi

exit "$rc"
