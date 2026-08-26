#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_u32(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"cannot parse integer value {value!r}")


def load_imports(layout: Path) -> list[str]:
    obj = json.loads(layout.read_text(encoding="utf-8"))
    return [str(item.get("name", "")) for item in obj.get("imports", [])]


def import_name_for_pc(pc: int, imports: list[str], import_base: int, import_stride: int) -> tuple[int, str] | None:
    if pc < import_base:
        return None
    delta = pc - import_base
    if delta % import_stride:
        return None
    index = delta // import_stride
    if index >= len(imports):
        return None
    return index, imports[index]


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect a PPC Lab JSON result")
    ap.add_argument("--result", required=True, type=Path)
    ap.add_argument("--layout", type=Path, help="optional relocation/import metadata JSON")
    ap.add_argument("--import-base", type=lambda x: int(x, 0), default=0x30000000)
    ap.add_argument("--import-stride", type=lambda x: int(x, 0), default=4)
    args = ap.parse_args()

    result = json.loads(args.result.read_text(encoding="utf-8"))
    stop = str(result.get("stop_reason", "unknown"))
    pc = parse_u32(result.get("pc", 0))
    insn = parse_u32(result.get("instruction", 0))
    print(f"stop_reason={stop}")
    print(f"pc=0x{pc:08x}")
    print(f"instruction=0x{insn:08x}")
    print(f"instructions={result.get('instructions', 0)}")

    if stop == "import_trap":
        if args.layout and args.layout.is_file():
            imports = load_imports(args.layout)
            resolved = import_name_for_pc(pc, imports, args.import_base, args.import_stride)
            if resolved:
                index, name = resolved
                print(f"import_index={index}")
                print(f"import_name={name}")
                print(f"import_address=0x{pc:08x}")
            else:
                print("import_name=<unresolved>")
        else:
            print("import_name=<layout metadata not supplied>")

    for i, dump in enumerate(result.get("dumps", [])):
        print(
            f"dump[{i}] address={dump.get('address')} size={dump.get('size')} "
            f"fnv1a64={dump.get('fnv1a64', '<legacy-result>')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
