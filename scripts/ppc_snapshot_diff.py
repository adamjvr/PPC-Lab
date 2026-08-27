#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministically compare two ppc-lab-snapshot-v1 files."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def keyed(items, key): return {str(x.get(key)): x for x in items}

def main() -> int:
    ap=argparse.ArgumentParser(description="Compare two PPC Lab snapshots")
    ap.add_argument("left", type=Path); ap.add_argument("right", type=Path)
    ap.add_argument("--json", type=Path); ap.add_argument("--ignore-backend", action="store_true")
    ns=ap.parse_args(); a=json.loads(ns.left.read_text()); b=json.loads(ns.right.read_text())
    if a.get("schema")!="ppc-lab-snapshot-v1" or b.get("schema")!="ppc-lab-snapshot-v1": raise SystemExit("snapshot schema mismatch")
    differences=[]
    for key in ("stop_reason","instructions","pc","instruction"):
        if a.get(key)!=b.get(key): differences.append({"field":key,"left":a.get(key),"right":b.get(key)})
    if not ns.ignore_backend and a.get("backend")!=b.get("backend"): differences.append({"field":"backend","left":a.get("backend"),"right":b.get("backend")})
    ac=a.get("cpu",{}); bc=b.get("cpu",{})
    for key in ("gpr","fpr_bits","lr","ctr","cr","xer","fpscr"):
        if ac.get(key)!=bc.get(key): differences.append({"field":"cpu."+key,"left":ac.get(key),"right":bc.get(key)})
    ar=keyed(a.get("regions",[]),"name"); br=keyed(b.get("regions",[]),"name")
    for name in sorted(set(ar)|set(br)):
        x,y=ar.get(name),br.get(name)
        if x is None or y is None or (x.get("base"),x.get("size"),x.get("perms"),x.get("fnv1a64")) != (y.get("base"),y.get("size"),y.get("perms"),y.get("fnv1a64")):
            differences.append({"field":"region:"+name,"left":x,"right":y})
    report={"schema":"ppc-lab-snapshot-diff-v1","equal":not differences,"differences":differences}
    text=json.dumps(report,indent=2)+"\n"; print(text,end="")
    if ns.json: ns.json.write_text(text,encoding="utf-8")
    return 0 if not differences else 1
if __name__=="__main__": raise SystemExit(main())
