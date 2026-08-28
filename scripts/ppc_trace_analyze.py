#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Analyze a PPC Lab instruction trace into coverage and dynamic CFG evidence."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from ppc_trace_intelligence import analyze_trace

def esc(s):return s.replace('\\','\\\\').replace('"','\\"')
def write_dot(path,a):
    lines=["digraph ppc_lab_trace {","  rankdir=TB;","  node [shape=box,fontname=monospace];"]
    for b in a.get("blocks",[]):
        label=f"{b['start']}..{b['end']}\\n{b.get('function','<unknown>')}\\nexec={b['executions']} insn={b['instruction_count']}"; lines.append(f'  {b["id"]} [label="{esc(label)}"];')
    for e in a.get("edges",[]):lines.append(f'  {e["source"]} -> {e["target"]} [label="{e["kind"]} x{e["count"]}"];')
    lines.append("}"); path.write_text("\n".join(lines)+"\n")
def report(a,top):
    s=a["summary"]; out=["PPC Lab trace analysis",f"events={s['events']} unique_pcs={s['unique_pcs']} covered_bytes={s['covered_bytes']} density={s['coverage_density']:.4f}",f"dynamic_blocks={s['dynamic_blocks']} unique_blocks={s['unique_blocks']} unique_edges={s['unique_edges']} call_edges={s['call_edges']}","","Hot PCs:"]
    for x in a.get("hot_pcs",[])[:top]:out.append(f"  {x['count']:>8}  {x['pc']}  {x.get('disassembly','')}"+(f" [{x['symbol']}]" if x.get('symbol') else ""))
    out += ["","Hot functions:"]
    for x in a.get("functions",[])[:top]:out.append(f"  {x['instructions_executed']:>8}  {x['name']}")
    if a.get("calls"):
        out += ["","Observed calls:"]
        for x in a["calls"][:top]:out.append(f"  {x['count']:>8}  {x['caller']} -> {x['callee']} @ {x['site']} -> {x['target']}")
    return "\n".join(out)+"\n"
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("trace",type=Path);ap.add_argument("--json",type=Path);ap.add_argument("--dot",type=Path);ap.add_argument("--top",type=int,default=20);ns=ap.parse_args();a=analyze_trace(json.loads(ns.trace.read_text()))
    if ns.json:ns.json.write_text(json.dumps(a,indent=2,sort_keys=True)+"\n")
    if ns.dot:write_dot(ns.dot,a)
    print(report(a,max(0,ns.top)),end="");return 0
if __name__=="__main__":raise SystemExit(main())
