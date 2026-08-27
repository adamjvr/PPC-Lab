#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Dependency-free reproducible PPC Lab batch/sweep experiment runner."""
from __future__ import annotations
import argparse, itertools, json, subprocess
from pathlib import Path


def safe(name:str)->str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:100] or "case"

def main()->int:
    ap=argparse.ArgumentParser(description="Run a PPC Lab experiment manifest")
    ap.add_argument("manifest",type=Path); ap.add_argument("--ppc-lab",type=Path,default=Path("./build/release/ppc-lab")); ap.add_argument("--out",type=Path,required=True)
    ns=ap.parse_args(); m=json.loads(ns.manifest.read_text());
    if m.get("schema")!="ppc-lab-experiment-v1": raise SystemExit("unsupported experiment schema")
    ns.out.mkdir(parents=True,exist_ok=True); base=[str(x) for x in m.get("base_args",[])]
    cases=[dict(x) for x in m.get("cases",[])]
    sweep=m.get("sweep",{})
    if sweep:
        keys=list(sweep); vals=[sweep[k] for k in keys]
        for combo in itertools.product(*vals):
            assignments=dict(zip(keys,combo)); args=[]; label=[]
            for key,val in assignments.items(): args += ["--set",f"{key}={val}"]; label.append(f"{key}-{val}")
            cases.append({"name":"_".join(label),"args":args,"parameters":assignments})
    results=[]; failures=0
    for idx,case in enumerate(cases):
        name=safe(str(case.get("name",f"case-{idx:03d}"))); snapshot=ns.out/f"{idx:03d}-{name}.snapshot.json"
        cmd=[str(ns.ppc_lab),"call"]+base+[str(x) for x in case.get("args",[])]+["--snapshot",str(snapshot)]
        p=subprocess.run(cmd,text=True,capture_output=True); failures += int(p.returncode!=0)
        results.append({"name":name,"parameters":case.get("parameters",{}),"exit_code":p.returncode,"snapshot":snapshot.name,"stdout":p.stdout,"stderr":p.stderr,"command":cmd})
    summary={"schema":"ppc-lab-experiment-results-v1","manifest":str(ns.manifest),"cases":results,"failed":failures}
    (ns.out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(f"cases={len(results)} failed={failures} summary={ns.out/'summary.json'}")
    return 0 if failures==0 else 1
if __name__=="__main__": raise SystemExit(main())
