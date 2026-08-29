#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, struct, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CLI=Path(sys.argv[1]).resolve(); SEC=ROOT/'scripts/ppc_lab_security.py'; API=ROOT/'scripts/ppc_lab_api.py'; EVID=ROOT/'scripts/ppc_lab_evidence.py'
def run(*args):
 p=subprocess.run([sys.executable,*map(str,args)],text=True,capture_output=True); assert p.returncode==0,(p.stdout,p.stderr); return json.loads(p.stdout) if p.stdout.strip().startswith('{') else p.stdout.strip()
def req(url,token=None,body=None):
 data=None if body is None else json.dumps(body).encode(); h={'Accept':'application/json'}
 if data is not None:h['Content-Type']='application/json'
 if token:h['Authorization']='Bearer '+token
 r=urllib.request.Request(url,data=data,headers=h,method='POST' if data is not None else 'GET')
 try:
  with urllib.request.urlopen(r,timeout=15) as x:return x.status,json.loads(x.read())
 except urllib.error.HTTPError as x:return x.code,json.loads(x.read())
with tempfile.TemporaryDirectory(prefix='ppclab-security-') as td0:
 td=Path(td0); store=td/'auth.json'; audit=td/'audit.jsonl'
 run(SEC,'init',store,'--json')
 viewer=run(SEC,'issue',store,'--role','viewer','--label','viewer','--json'); runner=run(SEC,'issue',store,'--role','runner','--label','runner','--json'); researcher=run(SEC,'issue',store,'--role','researcher','--label','researcher','--json')
 assert 'token' in viewer and viewer['token'] not in store.read_text()
 assert run(SEC,'verify',store,viewer['token'],'--require','evidence:read','--json')['ok']
 denied=subprocess.run([sys.executable,str(SEC),'verify',str(store),viewer['token'],'--require','execute:run','--json'],text=True,capture_output=True); assert denied.returncode==1
 code=td/'leaf.bin'; code.write_bytes(struct.pack('>II',0x3860002A,0x4E800020))
 evstore=td/'evidence'; run(EVID,'init',evstore)
 digest=hashlib.sha256(code.read_bytes()).hexdigest(); rec={'schema':'ppc-lab-fleet-job-result-v1','name':'secure-evidence','source':'test','cache_key':'a'*64,'engine_version':'3.9.0','host':'unit','inputs':{'image.path':{'logical_path':'leaf.bin','size':8,'sha256':digest}},'response':{'schema':'ppc-lab-worker-response-v1','id':'e','ok':True,'exit_code':0,'timed_out':False,'engine_version':'3.9.0','result':{'schema':'ppc-lab-result-v1','backend':'builtin-ppc32be','stop_reason':'return','instructions':2,'pc':'0x10000004','registers':{'r3':'0x0000002a'},'dumps':[]}}}
 ef=td/'e.json'; ef.write_text(json.dumps(rec)); run(EVID,'ingest',evstore,ef,'--json')
 ready=td/'ready.json'; proc=subprocess.Popen([sys.executable,str(API),'--ppc-lab',str(CLI),'--root',str(td),'--evidence-store',str(evstore),'--auth-store',str(store),'--audit-log',str(audit),'--port','0','--write-ready',str(ready)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  end=time.time()+15
  while time.time()<end and not ready.exists():
   if proc.poll() is not None: raise AssertionError(proc.stderr.read())
   time.sleep(.05)
  base=json.loads(ready.read_text())['url']
  assert req(base+'/v1/health')[0]==401
  assert req(base+'/v1/health',viewer['token'])[0]==200
  assert req(base+'/v1/evidence/report',viewer['token'])[0]==200
  job={'schema':'ppc-lab-job-v1','id':'secure-run','image':{'path':'leaf.bin','kind':'raw','code_base':'0x10000000'},'execution':{'backend':'builtin','entry':'0x10000000','max_instructions':100}}
  assert req(base+'/v1/run',viewer['token'],job)[0]==403
  st,res=req(base+'/v1/run',runner['token'],job); assert st==200 and res['ok'] and res['result']['registers']['r3']=='0x0000002a'
  assert req(base+'/v1/evidence/report',runner['token'])[0]==403
  assert req(base+'/v1/run',researcher['token'],job)[0]==200 and req(base+'/v1/evidence/report',researcher['token'])[0]==200
 finally:
  proc.terminate(); proc.wait(timeout=5)
 check=run(SEC,'audit-verify',audit,'--json'); assert check['ok'] and check['records']>=7
 subprocess.run([sys.executable,str(SEC),'revoke',str(store),viewer['token_id'],'--json'],check=True,capture_output=True,text=True)
 assert subprocess.run([sys.executable,str(SEC),'verify',str(store),viewer['token'],'--json'],capture_output=True,text=True).returncode==1
 rotated=run(SEC,'rotate',store,runner['token_id'],'--json'); assert rotated['replaces']==runner['token_id'] and run(SEC,'verify',store,rotated['token'],'--require','execute:run','--json')['ok']
 tampered=td/'bad-audit.jsonl'; lines=audit.read_text().splitlines(); first=json.loads(lines[0]); first['allowed']=not first.get('allowed',False); lines[0]=json.dumps(first); tampered.write_text('\n'.join(lines)+'\n')
 bad=subprocess.run([sys.executable,str(SEC),'audit-verify',str(tampered),'--json'],text=True,capture_output=True); assert bad.returncode==1
 guard=subprocess.run([sys.executable,str(API),'--ppc-lab',str(CLI),'--host','192.0.2.1','--port','0'],text=True,capture_output=True); assert guard.returncode!=0 and 'requires --auth-store or --token' in guard.stderr
print('PASS: scoped tokens, API least privilege, rotation/revocation, audit-chain verification, and remote bind guard')
