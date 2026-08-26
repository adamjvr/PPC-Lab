#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211


def fnv1a64(data: bytes) -> int:
    value = FNV_OFFSET
    for byte in data:
        value ^= byte
        value = (value * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def parse_hex_dump(text: str) -> bytes:
    if text == "<unreadable>":
        raise ValueError("PPC dump is unreadable")
    return bytes.fromhex(text)


def decode_float32(data: bytes, endian: str) -> list[float]:
    if len(data) % 4:
        raise ValueError("float32 comparison requires a byte count divisible by four")
    prefix = ">" if endian == "be" else "<"
    return [item[0] for item in struct.iter_unpack(prefix + "f", data)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare a PPC harness memory dump with a native/reference binary")
    ap.add_argument("--ppc", required=True, type=Path, help="ppc-lab-result-v1 JSON")
    ap.add_argument("--dump-index", type=int, default=0)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--mode", choices=["bytes", "float32"], default="bytes")
    ap.add_argument("--reference-endian", choices=["le", "be"], default="le")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    result = json.loads(args.ppc.read_text(encoding="utf-8"))
    dumps = result.get("dumps", [])
    if args.dump_index < 0 or args.dump_index >= len(dumps):
        raise SystemExit(f"dump index {args.dump_index} is out of range (dumps={len(dumps)})")

    ppc_bytes = parse_hex_dump(str(dumps[args.dump_index].get("hex", "")))
    ref_bytes = args.reference.read_bytes()
    report: dict[str, object] = {
        "schema": "ppc-lab-dump-comparison-v1",
        "mode": args.mode,
        "ppc_bytes": len(ppc_bytes),
        "reference_bytes": len(ref_bytes),
        "ppc_fnv1a64": f"0x{fnv1a64(ppc_bytes):016x}",
        "reference_fnv1a64": f"0x{fnv1a64(ref_bytes):016x}",
        "exact_bytes": ppc_bytes == ref_bytes,
    }

    if args.mode == "float32":
        ppc_values = decode_float32(ppc_bytes, "be")
        ref_values = decode_float32(ref_bytes, args.reference_endian)
        count = min(len(ppc_values), len(ref_values))
        if count == 0:
            raise SystemExit("no float32 values to compare")
        sum_sq = 0.0
        max_error = 0.0
        first_difference: int | None = None
        exact_float_bits = len(ppc_values) == len(ref_values)
        for i in range(count):
            a = ppc_values[i]
            b = ref_values[i]
            if math.isnan(a) and math.isnan(b):
                error = 0.0
            else:
                error = abs(a - b)
            sum_sq += error * error
            max_error = max(max_error, error)
            ppc_bits = struct.unpack(">I", ppc_bytes[i * 4 : i * 4 + 4])[0]
            ref_prefix = ">" if args.reference_endian == "be" else "<"
            ref_bits = struct.unpack(ref_prefix + "I", ref_bytes[i * 4 : i * 4 + 4])[0]
            if ppc_bits != ref_bits:
                exact_float_bits = False
                if first_difference is None:
                    first_difference = i
        report.update(
            {
                "ppc_float32_count": len(ppc_values),
                "reference_float32_count": len(ref_values),
                "compared_float32_count": count,
                "exact_float32_bits": exact_float_bits,
                "first_difference": first_difference,
                "rms_error": math.sqrt(sum_sq / count),
                "max_abs_error": max_error,
            }
        )

    print(json.dumps(report, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if bool(report["exact_bytes"]) or args.mode == "float32" else 1


if __name__ == "__main__":
    raise SystemExit(main())
