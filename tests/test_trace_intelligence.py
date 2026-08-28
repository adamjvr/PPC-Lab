#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json,struct,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CLI=Path(sys.argv[1]);PYTHON=sys.executable
def event(pc,word,dis,sym=""):return {"pc":f"0x{pc:08x}","instruction":f"0x{word:08x}","disassembly":dis,"symbol":sym}
with tempfile.TemporaryDirectory() as raw:
 td=Path(raw);code=td/'leaf.bin';code.write_bytes(struct.pack('>II',0x3860002a,0x4e800020));tr=td/'real.trace.json'
 subprocess.run([PYTHON,str(ROOT/'scripts/ppc_trace_capture.py'),'--ppc-lab',str(CLI),'--json',str(tr),'--','--code',str(code),'--entry','0x10000000','--backend','builtin'],check=True,capture_output=True,text=True)
 an=td/'real.analysis.json';dot=td/'real.dot';p=subprocess.run([PYTHON,str(ROOT/'scripts/ppc_trace_analyze.py'),str(tr),'--json',str(an),'--dot',str(dot)],check=True,capture_output=True,text=True);a=json.loads(an.read_text());assert a['schema']=='ppc-lab-trace-analysis-v1' and a['summary']['events']==2 and a['summary']['unique_pcs']==2 and a['summary']['covered_bytes']==8 and 'digraph ppc_lab_trace' in dot.read_text() and 'events=2' in p.stdout
 left={'schema':'ppc-lab-trace-v1','exit_code':0,'events':[event(0x1000,0x48000011,'bl 0x00001010','main'),event(0x1010,0x38630001,'addi r3,r3,1','worker'),event(0x1014,0x4e800020,'blr','worker+0x4'),event(0x1004,0x4800000d,'bl 0x00001010','main+0x4'),event(0x1010,0x38630001,'addi r3,r3,1','worker'),event(0x1014,0x4e800020,'blr','worker+0x4'),event(0x1008,0x4e800020,'blr','main+0x8')]}
 right={'schema':'ppc-lab-trace-v1','exit_code':0,'events':[event(0x1000,0x48000011,'bl 0x00001010','main'),event(0x1010,0x38630001,'addi r3,r3,1','worker'),event(0x1014,0x4e800020,'blr','worker+0x4'),event(0x1004,0x4800000d,'bl 0x00001010','main+0x4'),event(0x1010,0x38630001,'addi r3,r3,1','worker'),event(0x1010,0x38630001,'addi r3,r3,1','worker'),event(0x1014,0x4e800020,'blr','worker+0x4'),event(0x1008,0x4e800020,'blr','main+0x8')]}
 lp,rp=td/'l.json',td/'r.json';lp.write_text(json.dumps(left));rp.write_text(json.dumps(right));la=td/'la.json';subprocess.run([PYTHON,str(ROOT/'scripts/ppc_trace_analyze.py'),str(lp),'--json',str(la)],check=True,capture_output=True,text=True);x=json.loads(la.read_text());assert x['summary']['events']==7 and x['summary']['call_edges']==2 and sum(c['count'] for c in x['calls'] if c['caller']=='main' and c['callee']=='worker')==2
 df=td/'diff.json';d=subprocess.run([PYTHON,str(ROOT/'scripts/ppc_trace_diff.py'),str(lp),str(rp),'--json',str(df)],check=True,capture_output=True,text=True);o=json.loads(df.read_text());assert o['schema']=='ppc-lab-trace-diff-v1' and not o['equal'] and o['coverage']['jaccard']==1.0 and any(z['pc']=='0x00001010' and z['delta']==1 for z in o['pc_count_deltas']) and 'equal=false' in d.stdout;assert subprocess.run([PYTHON,str(ROOT/'scripts/ppc_trace_diff.py'),str(lp),str(rp),'--fail-on-diff'],capture_output=True,text=True).returncode==1
print('trace intelligence tests passed')
