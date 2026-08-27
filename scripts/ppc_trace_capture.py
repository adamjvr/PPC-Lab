#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Capture PPC Lab's symbolized textual trace into machine-readable JSON."""
from __future__ import annotations
import argparse,json,re,subprocess
from pathlib import Path
RX=re.compile(r"^(0x[0-9a-fA-F]{8})\s+(0x[0-9a-fA-F]{8})\s+(.*?)(?:\s+\[([^\]]+)\])?$")
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--ppc-lab",type=Path,default=Path("./build/release/ppc-lab")); ap.add_argument("--json",type=Path,required=True); ap.add_argument("args",nargs=argparse.REMAINDER); ns=ap.parse_args()
    extra=ns.args[1:] if ns.args[:1]==["--"] else ns.args
    cmd=[str(ns.ppc_lab),"call"]+extra+["--trace"]
    p=subprocess.run(cmd,text=True,capture_output=True); events=[]; other=[]
    for line in p.stderr.splitlines():
        m=RX.match(line)
        if m: events.append({"pc":m.group(1).lower(),"instruction":m.group(2).lower(),"disassembly":m.group(3).strip(),"symbol":m.group(4) or ""})
        elif line.strip(): other.append(line)
    obj={"schema":"ppc-lab-trace-v1","exit_code":p.returncode,"command":cmd,"events":events,"stderr_unparsed":other,"stdout":p.stdout}
    ns.json.write_text(json.dumps(obj,indent=2)+"\n"); print(f"events={len(events)} trace={ns.json}")
    return p.returncode
if __name__=="__main__": raise SystemExit(main())
