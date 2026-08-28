#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'scripts'/'ppc_lab_knowledge.py'
EVIDENCE=ROOT/'scripts'/'ppc_lab_evidence.py'
PY=sys.executable

def run(*args:str, tool:Path=TOOL):
    return subprocess.run([PY,str(tool),*args],text=True,capture_output=True,check=False)

def put(path:Path, doc:dict):
    path.write_text(json.dumps(doc,indent=2)+"\n",encoding='utf-8')

with tempfile.TemporaryDirectory(prefix='ppclab-knowledge-') as raw:
    td=Path(raw); graph=td/'graph'
    a=hashlib.sha256(b'target-a').hexdigest(); b=hashlib.sha256(b'target-b').hexdigest()
    assert run('init',str(graph),'--json').returncode==0

    metadata={'schema':'ppc-lab-metadata-v1','format':'ELF32-PPC-BE','entry':'0x10000000','symbols':[
        {'address':'0x10000000','name':'entry_fn'},{'address':'0x10000010','name':'helper_fn'}]}
    trace={'schema':'ppc-lab-trace-analysis-v1','summary':{},'hot_pcs':[
        {'pc':'0x10000000','count':4,'disassembly':'bl 0x10000010','function':'entry_fn'},
        {'pc':'0x10000010','count':4,'disassembly':'blr','function':'helper_fn'}],
        'functions':[{'name':'entry_fn','instructions_executed':4},{'name':'helper_fn','instructions_executed':4}],
        'blocks':[],'edges':[],'calls':[{'caller':'entry_fn','callee':'helper_fn','site':'0x10000000','target':'0x10000010','count':4}]}
    result={'schema':'ppc-lab-fleet-job-result-v1','name':'probe-a','inputs':{'image.path':{'sha256':a,'size':8,'logical_path':'a.bin'}},
        'response':{'schema':'ppc-lab-worker-response-v1','ok':True,'exit_code':0,'engine_version':'2.4.0','result':{
            'schema':'ppc-lab-result-v1','backend':'builtin-ppc32be','stop_reason':'return','pc':'0x10000010','instructions':2,
            'registers':{'r3':'0x0000002a'},'cr':'0x00000000','lr':'0x00000000','ctr':'0x00000000','dumps':[]}}}
    result_b=json.loads(json.dumps(result)); result_b['name']='probe-b'; result_b['inputs']['image.path']['sha256']=b; result_b['inputs']['image.path']['logical_path']='b.bin'
    corpus={'schema':'ppc-lab-corpus-case-v1','id':'case-a','description':'regression A','tags':['smoke'],
        'inputs':[{'field':'image.path','sha256':a,'size':8,'path_hint':'a.bin'}],'job':{},'expectation':result['response']['result']}
    triage={'schema':'ppc-lab-differential-triage-v1','equal':False,'classification':'control-flow','summary':{},
        'first_divergence':{'left':{'pc':'0x10000000'},'right':{'pc':'0x10000010'}},'resynchronization':None,'window':{},'alignment':[],
        'run':{'inputs':[{'field':'image.path','sha256':a,'size':8,'path_hint':'a.bin'}]}}
    campaign={'schema':'ppc-lab-campaign-summary-v1','status':'complete-with-findings','name':'campaign-a','engine_version':'2.4.0',
        'manifest_sha256':'1'*64,'out':'out','exploration':{'input_provenance':[{'sha256':a,'size':8,'field':'image.path'}]}}
    evidence={'schema':'ppc-lab-evidence-v1','target_sha256':a,'format':'ELF32-PPC-BE','entry':'0x10000000','symbols':metadata['symbols'],
        'annotations':[{'address':'0x10000010','kind':'manual-finding','comment':'state field candidate'}]}

    docs=td/'docs'; docs.mkdir()
    for name,doc in [('metadata.json',metadata),('trace.json',trace),('result-a.json',result),('result-b.json',result_b),('corpus.json',corpus),('triage.json',triage),('campaign.json',campaign),('evidence.json',evidence)]: put(docs/name,doc)
    # Targetless loader/trace evidence can be scoped explicitly when the researcher knows the image hash.
    assert run('ingest',str(graph),str(docs/'metadata.json'),str(docs/'trace.json'),'--target-sha256',a,'--json').returncode==0
    ing=run('ingest',str(graph),*[str(x) for x in sorted(docs.glob('*.json')) if x.name not in ('metadata.json','trace.json')],'--json')
    assert ing.returncode==0,(ing.stdout,ing.stderr)
    info=json.loads(ing.stdout); assert info['added']>=5

    q=json.loads(run('query',str(graph),'--type','target','--json').stdout); assert q['count']==2
    fq=json.loads(run('query',str(graph),'--type','function','--target-sha256',a[:16],'--json').stdout); assert {x['label'] for x in fq['results']}=={'entry_fn','helper_fn'}
    bq=json.loads(run('query',str(graph),'--type','behavior','--json').stdout); assert bq['count']>=1
    shared=None
    for candidate in bq['results']:
        rel=run('related',str(graph),candidate['key'],'--depth','2','--json'); assert rel.returncode==0,rel.stderr
        related=json.loads(rel.stdout); target_keys={x['key'] for x in related['nodes'] if x['type']=='target'}
        if f'target:{a}' in target_keys and f'target:{b}' in target_keys:
            shared=candidate['key']; break
    assert shared is not None, 'expected a behavior fingerprint shared across two target hashes'
    path=run('path',str(graph),f'target:{a}',f'function:{a}:helper_fn','--json'); assert path.returncode==0,path.stderr; assert json.loads(path.stdout)['found']

    export=td/'decompiler.json'; ex=run('export-decompiler',str(graph),'--target-sha256',a[:20],'--json',str(export)); assert ex.returncode==0,(ex.stdout,ex.stderr)
    edoc=json.loads(export.read_text()); assert edoc['schema']=='ppc-lab-evidence-v1' and edoc['target_sha256']==a
    assert any(x['name']=='entry_fn' for x in edoc['symbols'])
    kinds={x['kind'] for x in edoc['annotations']}; assert 'execution' in kinds and 'observed-call' in kinds and 'differential-divergence' in kinds and 'manual-finding' in kinds

    report=json.loads(run('report',str(graph),'--json').stdout); assert report['schema']=='ppc-lab-knowledge-report-v1' and report['targets']==2 and report['relations']['observed-call']>=1
    verify=json.loads(run('verify',str(graph),'--json').stdout); assert verify['ok'] is True

    # Existing evidence stores can be synchronized without copying target binaries.
    store=td/'evidence-store'; assert run('init',str(store),tool=EVIDENCE).returncode==0
    evdir=td/'ev'; evdir.mkdir(); put(evdir/'record.json',result)
    er=run('ingest',str(store),str(evdir),'--json',tool=EVIDENCE); assert er.returncode==0,(er.stdout,er.stderr)
    before=report['documents']; sr=run('sync-evidence',str(graph),str(store),'--json'); assert sr.returncode==0,(sr.stdout,sr.stderr)
    sdoc=json.loads(sr.stdout); assert sdoc['indexed_artifacts']==1 and sdoc['deduplicated']>=1
    assert json.loads(run('report',str(graph),'--json').stdout)['documents']>=before

print('PASS: research knowledge graph, cross-target behavior links, evidence sync, paths, and decompiler export')
