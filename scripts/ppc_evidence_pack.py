#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Combine PPC Lab metadata, snapshots and traces into decompiler-neutral evidence."""
from __future__ import annotations
import argparse,collections,json
from pathlib import Path
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--metadata",type=Path,required=True); ap.add_argument("--snapshot",type=Path); ap.add_argument("--trace",type=Path); ap.add_argument("--json",type=Path,required=True); ns=ap.parse_args()
    md=json.loads(ns.metadata.read_text()); snap=json.loads(ns.snapshot.read_text()) if ns.snapshot else None; trace=json.loads(ns.trace.read_text()) if ns.trace else None
    annotations=[]
    if snap:
        pc=str(snap.get("pc","0x00000000")); annotations.append({"address":pc,"kind":"snapshot-stop","comment":f"PPC Lab: stop={snap.get('stop_reason')} instructions={snap.get('instructions')} backend={snap.get('backend')}"})
    if trace:
        counts=collections.Counter(e.get("pc") for e in trace.get("events",[]) if e.get("pc"))
        first={e.get("pc"):e for e in trace.get("events",[]) if e.get("pc")}
        for pc,count in counts.items():
            e=first[pc]; label=f" symbol={e.get('symbol')}" if e.get('symbol') else ""
            annotations.append({"address":pc,"kind":"execution","comment":f"PPC Lab: executed {count}x; {e.get('disassembly','')}{label}"})
    obj={"schema":"ppc-lab-evidence-v1","format":md.get("format"),"entry":md.get("entry"),"symbols":md.get("symbols",[]),"annotations":annotations}
    ns.json.write_text(json.dumps(obj,indent=2)+"\n"); print(f"symbols={len(obj['symbols'])} annotations={len(annotations)} evidence={ns.json}"); return 0
if __name__=="__main__": raise SystemExit(main())
