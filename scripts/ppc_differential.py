#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run two PPC Lab configurations and compare deterministic snapshots."""
from __future__ import annotations
import argparse,json,subprocess,tempfile,sys
from pathlib import Path

def main()->int:
    ap=argparse.ArgumentParser(description="Differential PPC Lab execution")
    ap.add_argument("manifest",type=Path); ap.add_argument("--ppc-lab",type=Path,default=Path("./build/release/ppc-lab")); ap.add_argument("--json",type=Path)
    ns=ap.parse_args(); m=json.loads(ns.manifest.read_text());
    if m.get("schema")!="ppc-lab-differential-v1": raise SystemExit("unsupported differential schema")
    base=[str(x) for x in m.get("base_args",[])]
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); snaps=[]; runs=[]
        for side in ("left","right"):
            snap=td/f"{side}.json"; cmd=[str(ns.ppc_lab),"call"]+base+[str(x) for x in m.get(side+"_args",[])]+["--snapshot",str(snap)]
            p=subprocess.run(cmd,text=True,capture_output=True); runs.append({"side":side,"exit_code":p.returncode,"stdout":p.stdout,"stderr":p.stderr,"command":cmd}); snaps.append(snap)
        diff=subprocess.run([sys.executable,str(Path(__file__).with_name("ppc_snapshot_diff.py")),str(snaps[0]),str(snaps[1]),"--ignore-backend"],text=True,capture_output=True)
        report={"schema":"ppc-lab-differential-result-v1","equal":diff.returncode==0,"runs":runs,"diff":json.loads(diff.stdout)}
    text=json.dumps(report,indent=2)+"\n"; print(text,end="")
    if ns.json: ns.json.write_text(text)
    return 0 if report["equal"] else 1
if __name__=="__main__": raise SystemExit(main())
