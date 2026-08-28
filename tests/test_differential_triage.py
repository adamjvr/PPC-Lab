#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json, struct, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CLI=Path(sys.argv[1]); PY=sys.executable; TRI=ROOT/'scripts/ppc_lab_triage.py'; WORKER=ROOT/'scripts/ppc_lab_worker.py'
def ev(pc,word,dis): return {'pc':f'0x{pc:08x}','instruction':f'0x{word:08x}','disassembly':dis,'symbol':''}
with tempfile.TemporaryDirectory(prefix='ppclab-triage-') as raw:
 td=Path(raw)
 left={'schema':'ppc-lab-trace-v1','exit_code':0,'events':[ev(0x1000,1,'a'),ev(0x1004,2,'b'),ev(0x1008,3,'c'),ev(0x100c,4,'d'),ev(0x1010,5,'e')]}
 right={'schema':'ppc-lab-trace-v1','exit_code':0,'events':[ev(0x1000,1,'a'),ev(0x1004,2,'b'),ev(0x2000,9,'x'),ev(0x2004,10,'y'),ev(0x100c,4,'d'),ev(0x1010,5,'e')]}
 lp=td/'left.json';rp=td/'right.json';lp.write_text(json.dumps(left));rp.write_text(json.dumps(right));out=td/'triage.json';bundle=td/'bundle'
 p=subprocess.run([PY,str(TRI),'compare',str(lp),str(rp),'--json',str(out),'--bundle',str(bundle),'--fail-on-diff'],text=True,capture_output=True)
 assert p.returncode==1,p.stderr
 r=json.loads(out.read_text());assert r['schema']=='ppc-lab-differential-triage-v1' and not r['equal'] and r['classification']=='control-flow';assert r['summary']['common_prefix_events']==2;assert r['first_divergence']['left']['pc']=='0x00001008' and r['first_divergence']['right']['pc']=='0x00002000';assert r['resynchronization']['left_index']==3 and r['resynchronization']['right_index']==4;assert (bundle/'manifest.json').is_file() and (bundle/'README.md').is_file()
 # End-to-end identical backend run: exercise worker invocation, trace parsing, snapshots, provenance and repro-safe bundle generation.
 code=td/'leaf.bin';code.write_bytes(struct.pack('>II',0x3860002a,0x4e800020));job=td/'job.json';job.write_text(json.dumps({'schema':'ppc-lab-job-v1','id':'triage-e2e','image':{'kind':'raw','path':'leaf.bin','code_base':'0x10000000'},'execution':{'entry':'0x10000000','backend':'builtin'}}))
 rout=td/'run.json';rb=td/'run-bundle';q=subprocess.run([PY,str(TRI),'run',str(job),'--left-ppc-lab',str(CLI),'--right-ppc-lab',str(CLI),'--left-worker',str(WORKER),'--right-worker',str(WORKER),'--left-backend','builtin','--right-backend','builtin','--json',str(rout),'--bundle',str(rb)],text=True,capture_output=True)
 assert q.returncode==0,(q.stdout,q.stderr);rr=json.loads(rout.read_text());assert rr['equal'] and rr['classification']=='equal' and rr['summary']['left_events']==2 and rr['snapshot']['equal'];assert rr['run']['inputs'][0]['sha256'] and (rb/'left.response.json').is_file() and (rb/'right.response.json').is_file() and (rb/'repro.job.json').is_file()
 # Snapshot-only difference reporting remains backend-neutral but catches architectural state.
 ls={'backend':'builtin','pc':'0x1000','cpu':{'gpr':[0,1,2]}};rs={'backend':'unicorn','pc':'0x1000','cpu':{'gpr':[0,9,2]}};lsp=td/'ls.json';rsp=td/'rs.json';lsp.write_text(json.dumps(ls));rsp.write_text(json.dumps(rs));so=td/'snap.json'
 subprocess.run([PY,str(TRI),'compare',str(lp),str(lp),'--left-snapshot',str(lsp),'--right-snapshot',str(rsp),'--json',str(so)],check=True,capture_output=True,text=True);sr=json.loads(so.read_text());assert not sr['equal'] and sr['classification']=='state-only' and not sr['snapshot']['equal'] and any(d['path']=='$.cpu.gpr[1]' for d in sr['snapshot']['differences'])
print('differential triage tests passed')
