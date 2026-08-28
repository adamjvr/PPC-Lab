#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json,struct,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CLI=Path(sys.argv[1]).resolve(); TOOL=ROOT/'scripts'/'ppc_lab_corpus.py'; WORKER=ROOT/'scripts'/'ppc_lab_worker.py'
def run(*a,check=False):
 r=subprocess.run([sys.executable,str(TOOL),'--ppc-lab',str(CLI),'--worker',str(WORKER),*map(str,a)],text=True,capture_output=True,check=False)
 if check and r.returncode: raise AssertionError((r.stdout,r.stderr))
 return r
with tempfile.TemporaryDirectory(prefix='ppclab-corpus-test-') as t:
 td=Path(t); inputs=td/'inputs'; inputs.mkdir(); code=inputs/'leaf.bin'; code.write_bytes(struct.pack('>II',0x3860002A,0x4E800020))
 job={'schema':'ppc-lab-job-v1','id':'leaf42','image':{'path':'inputs/leaf.bin','kind':'raw','code_base':'0x10000000'},'execution':{'backend':'builtin','entry':'0x10000000','max_instructions':100},'registers':{'r4':123},'dumps':[{'address':'0x10000000','size':8}]}
 jp=td/'job.json'; jp.write_text(json.dumps(job)); corpus=td/'corpus'
 p=run('promote',corpus,'--id','leaf42','--job',jp,'--description','synthetic leaf','--tag','smoke','--embed-input',check=True); assert 'promoted' in p.stdout
 p2=run('promote',corpus,'--id','leaf-private','--job',jp,'--description','external input baseline','--tag','private',check=True); assert 'promoted' in p2.stdout
 private=json.loads((corpus/'cases'/'leaf-private.json').read_text()); assert not private['inputs'][0].get('embedded')
 ext=run('replay',corpus,'--case','leaf-private','--input-root',td,check=True); assert 'PASS leaf-private' in ext.stdout
 v=run('verify',corpus,check=True); assert '2 corpus cases verified' in v.stdout
 summary=td/'summary.json'; rr=run('replay',corpus,'--case','leaf42','--backend','builtin','--json',summary,check=True); assert 'PASS leaf42' in rr.stdout
 s=json.loads(summary.read_text()); assert s['schema']=='ppc-lab-corpus-replay-summary-v1' and s['passed']==1
 casep=corpus/'cases'/'leaf42.json'; case=json.loads(casep.read_text()); assert case['inputs'][0]['embedded']; assert '$INPUT:0'==case['job']['image']['path']
 # Intentional expectation drift is reported, then can be blessed explicitly.
 case['expectation']['result']['registers']['r3']='0x0000002b'; casep.write_text(json.dumps(case))
 bad=run('replay',corpus,'--case','leaf42'); assert bad.returncode==1 and '$.result.registers.r3' in bad.stdout
 mini=td/'min.json'; m=run('minimize',corpus,'leaf42','--output',mini,check=True); mc=json.loads(mini.read_text()); assert 'registers.r4' in mc['minimized_removed'] and 'r4' not in mc['job'].get('registers',{})
 b=run('bless',corpus,'leaf42','--yes',check=True); assert 'blessed leaf42' in b.stdout; run('replay',corpus,'--case','leaf42',check=True)
 # Corruption of explicitly embedded input is detected before execution.
 obj=corpus/case['inputs'][0]['embedded']; original=obj.read_bytes(); obj.write_bytes(b'corrupt')
 broken=run('verify',corpus); assert broken.returncode==2 and 'corrupt embedded input' in broken.stderr; obj.write_bytes(original)
 run('verify',corpus,check=True)
print('PASS: behavioral corpus promotion/replay/bless/minimize/integrity')
