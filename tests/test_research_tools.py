#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json,struct,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CLI=Path(sys.argv[1])
with tempfile.TemporaryDirectory() as td:
    td=Path(td); code=td/'leaf.bin'; code.write_bytes(struct.pack('>II',0x3860002a,0x4e800020))
    a=td/'a.json'; b=td/'b.json'
    base=[str(CLI),'call','--code',str(code),'--entry','0x10000000','--backend','builtin']
    subprocess.run(base+['--snapshot',str(a)],check=True,capture_output=True,text=True)
    snap=json.loads(a.read_text()); assert snap['schema']=='ppc-lab-snapshot-v1'; assert snap['cpu']['gpr'][3]=='0x0000002a'; assert snap['regions']
    subprocess.run(base+['--snapshot',str(b)],check=True,capture_output=True,text=True)
    eq=subprocess.run([sys.executable,str(ROOT/'scripts/ppc_snapshot_diff.py'),str(a),str(b)],capture_output=True,text=True); assert eq.returncode==0 and json.loads(eq.stdout)['equal']
    # trace capture
    tr=td/'trace.json'; subprocess.run([sys.executable,str(ROOT/'scripts/ppc_trace_capture.py'),'--ppc-lab',str(CLI),'--json',str(tr),'--','--code',str(code),'--entry','0x10000000','--backend','builtin'],check=True,capture_output=True,text=True); assert len(json.loads(tr.read_text())['events'])==2
    # batch sweep
    manifest=td/'batch.json'; manifest.write_text(json.dumps({'schema':'ppc-lab-experiment-v1','base_args':['--code',str(code),'--entry','0x10000000','--backend','builtin'],'sweep':{'r4':['1','2','3']}}))
    out=td/'batch'; subprocess.run([sys.executable,str(ROOT/'scripts/ppc_lab_batch.py'),str(manifest),'--ppc-lab',str(CLI),'--out',str(out)],check=True,capture_output=True,text=True); summary=json.loads((out/'summary.json').read_text()); assert len(summary['cases'])==3 and summary['failed']==0
    # differential same/same
    diffm=td/'diff.json'; diffm.write_text(json.dumps({'schema':'ppc-lab-differential-v1','base_args':['--code',str(code),'--entry','0x10000000'],'left_args':['--backend','builtin'],'right_args':['--backend','builtin']}))
    dp=subprocess.run([sys.executable,str(ROOT/'scripts/ppc_differential.py'),str(diffm),'--ppc-lab',str(CLI)],capture_output=True,text=True); assert dp.returncode==0 and json.loads(dp.stdout)['equal']
    # evidence packing from synthetic metadata + real snapshot/trace
    md=td/'meta.json'; md.write_text(json.dumps({'schema':'ppc-lab-metadata-v1','format':'raw-test','entry':'0x10000000','symbols':[{'name':'leaf','address':'0x10000000','defined':True,'imported':False}]})); ev=td/'ev.json'
    subprocess.run([sys.executable,str(ROOT/'scripts/ppc_evidence_pack.py'),'--metadata',str(md),'--snapshot',str(a),'--trace',str(tr),'--json',str(ev)],check=True,capture_output=True,text=True); evidence=json.loads(ev.read_text()); assert evidence['schema']=='ppc-lab-evidence-v1' and evidence['annotations']
print('research-machine tooling tests passed')
