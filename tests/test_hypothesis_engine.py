#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; TOOL=ROOT/'scripts'/'ppc_lab_hypothesize.py'; KNOW=ROOT/'scripts'/'ppc_lab_knowledge.py'; PY=sys.executable

def put(p:Path,v): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def run(*args): return subprocess.run([PY,str(TOOL),*map(str,args)],text=True,capture_output=True,check=False)

with tempfile.TemporaryDirectory(prefix='ppclab-hyp-') as raw:
    td=Path(raw); exp=td/'exploration'; (exp/'cases').mkdir(parents=True)
    target=hashlib.sha256(b'private-target').hexdigest()
    manifest={'schema':'ppc-lab-exploration-v1','strategy':'guided','max_cases':16,
        'base_job':{'schema':'ppc-lab-job-v1','image':{'path':'target.bin'},'registers':{'r3':0}},
        'axes':[{'path':'registers.r3','values':[0,1000,2000,3000]}]}
    mp=td/'manifest.json'; put(mp,manifest)
    summary={'schema':'ppc-lab-exploration-summary-v1','strategy':'guided','manifest':str(mp),'evaluated_cases':4,'novel_cases':4,
        'successful_cases':4,'unique_pcs':4,'unique_behaviors':4,'promoted_cases':0,
        'input_provenance':[{'field':'image.path','sha256':target,'size':14}], 'cases':[]}
    put(exp/'summary.json',summary)
    for i,value in enumerate((0,1000,2000,3000)):
        behavior=hashlib.sha256(f'behavior-{i}'.encode()).hexdigest()
        row={'schema':'ppc-lab-exploration-case-v1','index':i,'parent':None,'assignment':{'registers.r3':value},'novel':True,
            'novelty':{'new_pcs':[f'0x1000000{i}'],'new_pc_count':1,'behavior_novel':True},'behavior_sha256':behavior,
            'trace':{'events':i+1,'unique_pcs':1,'pcs':[f'0x1000000{i}']},
            'worker':{'schema':'ppc-lab-worker-response-v1','ok':True,'exit_code':0,'engine_version':'2.5.0','result':{
                'schema':'ppc-lab-result-v1','stop_reason':'return','instructions':10+(i*10),'pc':f'0x1000000{i}','registers':{'r3':value+i},'dumps':[]}},
            'job':{'schema':'ppc-lab-job-v1','image':{'path':'target.bin'},'registers':{'r3':value}}}
        put(exp/'cases'/f'{i:05d}.json',row)
    report=td/'report.json'; p=run('analyze',exp,'--manifest',mp,'--json',report); assert p.returncode==0,(p.stdout,p.stderr)
    doc=json.loads(report.read_text()); assert doc['schema']=='ppc-lab-hypothesis-report-v1'; assert doc['input_provenance'][0]['sha256']==target
    h=doc['hypotheses'][0]; assert h['subject']=='registers.r3'; assert h['role']=='count-or-length'; assert h['confidence']>=0.55; assert len(h['supporting_cases'])>=2
    out=td/'experiments'; p=run('experiments',report,'--out',out); assert p.returncode==0,(p.stdout,p.stderr)
    generated=json.loads((out/f"{h['id']}.exploration.json").read_text()); assert generated['schema']=='ppc-lab-exploration-v1'; assert generated['axes'][0]['path']=='registers.r3'
    promoted=td/'promoted.json'; p=run('promote',report,h['id'],'--evidence',exp,'--json',promoted); assert p.returncode==0,(p.stdout,p.stderr)
    pd=json.loads(promoted.read_text()); assert pd['schema']=='ppc-lab-hypothesis-v1' and pd['status']=='supported'; assert len(pd['verified_support'])>=2
    graph=td/'graph'
    assert subprocess.run([PY,str(KNOW),'init',str(graph),'--json'],text=True,capture_output=True).returncode==0
    gi=subprocess.run([PY,str(KNOW),'ingest',str(graph),str(report),str(promoted),'--json'],text=True,capture_output=True)
    assert gi.returncode==0,(gi.stdout,gi.stderr)
    gq=subprocess.run([PY,str(KNOW),'query',str(graph),'--type','hypothesis','--json'],text=True,capture_output=True)
    qdoc=json.loads(gq.stdout); assert qdoc['count']>=1 and any('count/length' in x['label'] for x in qdoc['results'])
    # Tampering with evidence after analysis must invalidate promotion.
    case=exp/'cases'/'00001.json'; tampered=json.loads(case.read_text()); tampered['behavior_sha256']='0'*64; put(case,tampered)
    p=run('promote',report,h['id'],'--evidence',exp,'--json',td/'bad.json'); assert p.returncode==2 and 'changed since hypothesis analysis' in p.stderr
print('PASS: deterministic hypothesis inference, explicit experiments, evidence-gated promotion, and tamper detection')
