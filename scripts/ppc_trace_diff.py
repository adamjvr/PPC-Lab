#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compare two PPC Lab traces by coverage and dynamic behavior."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from ppc_trace_intelligence import analyze_trace,analysis_call_counts,analysis_function_counts,analysis_pc_counts
def rows(l,r,name):
    out=[]
    for k in sorted(set(l)|set(r)):
        a,b=int(l.get(k,0)),int(r.get(k,0))
        if a!=b:out.append({name:k,"left":a,"right":b,"delta":b-a})
    out.sort(key=lambda x:(-abs(x["delta"]),str(x[name])));return out
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("left",type=Path);ap.add_argument("right",type=Path);ap.add_argument("--json",type=Path);ap.add_argument("--top",type=int,default=20);ap.add_argument("--fail-on-diff",action="store_true");ns=ap.parse_args()
    la=analyze_trace(json.loads(ns.left.read_text()));ra=analyze_trace(json.loads(ns.right.read_text()));lp,rp=analysis_pc_counts(la),analysis_pc_counts(ra);lf,rf=analysis_function_counts(la),analysis_function_counts(ra);lc,rc=analysis_call_counts(la),analysis_call_counts(ra);ls,rs=set(lp),set(rp);u=ls|rs;i=ls&rs;pd=rows(lp,rp,"pc");fd=rows(lf,rf,"function");cd=[]
    for k in sorted(set(lc)|set(rc)):
        a,b=lc.get(k,0),rc.get(k,0)
        if a!=b:cd.append({"caller":k[0],"callee":k[1],"site":k[2],"target":k[3],"left":a,"right":b,"delta":b-a})
    cd.sort(key=lambda x:(-abs(x["delta"]),x["site"],x["target"]));eq=not pd and not fd and not cd
    obj={"schema":"ppc-lab-trace-diff-v1","equal":eq,"coverage":{"left_unique_pcs":len(ls),"right_unique_pcs":len(rs),"shared_unique_pcs":len(i),"union_unique_pcs":len(u),"jaccard":len(i)/len(u) if u else 1.0,"only_left":sorted(ls-rs),"only_right":sorted(rs-ls)},"pc_count_deltas":pd,"function_deltas":fd,"call_deltas":cd,"left_summary":la["summary"],"right_summary":ra["summary"]}
    if ns.json:ns.json.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
    print(f"equal={str(eq).lower()} coverage_jaccard={obj['coverage']['jaccard']:.6f} left_pcs={len(ls)} right_pcs={len(rs)}")
    for x in pd[:max(0,ns.top)]:print(f"pc {x['pc']}: {x['left']} -> {x['right']} ({x['delta']:+d})")
    return 1 if ns.fail_on_diff and not eq else 0
if __name__=="__main__":raise SystemExit(main())
