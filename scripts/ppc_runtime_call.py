#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run a native PPC image with a reusable runtime personality.

The runtime file maps imported symbol names to PPC Lab's deterministic behavioral
stub kinds. Matching imports are bound into the configured import-trap range;
unmatched imports stay explicit and will fail normally if reached.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path


def image_flag(path: Path) -> str:
    with path.open("rb") as f: b = f.read(8)
    if b.startswith(b"\x7fELF"): return "--elf"
    if b.startswith(b"Joy!"): return "--pef"
    if len(b) >= 4 and int.from_bytes(b[:4], "big") in (0xfeedface, 0xcafebabe): return "--macho"
    raise SystemExit(f"unsupported native image format: {path}")


def imports(ppc_lab: Path, image: Path) -> list[str]:
    p = subprocess.run([str(ppc_lab), "symbols", str(image)], text=True, capture_output=True)
    if p.returncode:
        raise SystemExit(p.stderr.strip() or p.stdout.strip() or "cannot inspect image symbols")
    found: list[str] = []
    for line in p.stdout.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) == 5 and parts[1] == "U": found.append(parts[4])
    return found


def main() -> int:
    ap=argparse.ArgumentParser(description="Run a PPC image with a reusable runtime personality")
    ap.add_argument("--ppc-lab", type=Path, default=Path("./build/release/ppc-lab"))
    ap.add_argument("--runtime", type=Path, required=True)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--import-base", type=lambda x:int(x,0), default=0x30000000)
    ap.add_argument("--import-stride", type=lambda x:int(x,0), default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="extra ppc-lab call arguments after --")
    ns=ap.parse_args()
    runtime=json.loads(ns.runtime.read_text(encoding="utf-8"))
    if runtime.get("schema") != "ppc-lab-runtime-v1": raise SystemExit("unsupported runtime schema")
    mapping={str(k):str(v) for k,v in runtime.get("symbols",{}).items()}
    matched=[]
    cmd=[str(ns.ppc_lab),"call",image_flag(ns.image),str(ns.image),"--import-base",hex(ns.import_base)]
    next_addr=ns.import_base
    for name in imports(ns.ppc_lab,ns.image):
        kind=mapping.get(name)
        if not kind: continue
        addr=next_addr; next_addr += ns.import_stride
        cmd += ["--bind",f"{name}={hex(addr)}","--stub",f"{kind}@{hex(addr)}"]
        matched.append({"name":name,"kind":kind,"address":f"0x{addr:08x}"})
    extra=ns.args[1:] if ns.args[:1]==["--"] else ns.args
    cmd += extra
    print(json.dumps({"runtime":runtime.get("name"),"matched_imports":matched,"command":cmd},indent=2),file=sys.stderr)
    if ns.dry_run: return 0
    return subprocess.run(cmd).returncode

if __name__=="__main__": raise SystemExit(main())
