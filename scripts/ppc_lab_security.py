#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab LTS scoped token and tamper-evident audit management."""
from __future__ import annotations
import argparse, base64, datetime as dt, hashlib, hmac, json, os, secrets, sys
from pathlib import Path
from typing import Any

STORE_SCHEMA='ppc-lab-auth-store-v1'
TOKEN_SCHEMA='ppc-lab-auth-token-v1'
AUDIT_SCHEMA='ppc-lab-audit-record-v1'
API_VERSION=1
PBKDF2_ROUNDS=120000
ROLES={
 'viewer': {'status:read','evidence:read'},
 'runner': {'status:read','execute:run'},
 'researcher': {'status:read','evidence:read','execute:run'},
 'admin': {'*'},
}
KNOWN_SCOPES={'status:read','evidence:read','execute:run','*'}
class SecurityError(RuntimeError): pass

def now()->str: return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
def canonical(v:Any)->bytes: return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def atomic_json(path:Path,doc:dict[str,Any],mode:int=0o600)->None:
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+f'.tmp-{os.getpid()}-{secrets.token_hex(4)}')
 tmp.write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n',encoding='utf-8'); os.chmod(tmp,mode); os.replace(tmp,path)
def load_store(path:Path)->dict[str,Any]:
 p=path.expanduser().resolve()
 try: doc=json.loads(p.read_text(encoding='utf-8'))
 except FileNotFoundError as exc: raise SecurityError(f'auth store does not exist: {p}') from exc
 if doc.get('schema')!=STORE_SCHEMA: raise SecurityError(f'unsupported auth store schema: {doc.get("schema")}')
 if not isinstance(doc.get('tokens'),dict): raise SecurityError('auth store tokens must be an object')
 return doc

def init_store(path:Path,force:bool=False)->dict[str,Any]:
 p=path.expanduser().resolve()
 if p.exists() and not force: raise SecurityError(f'auth store already exists: {p}')
 doc={'schema':STORE_SCHEMA,'security_api':API_VERSION,'created_at':now(),'tokens':{}}
 atomic_json(p,doc); return {'schema':'ppc-lab-auth-result-v1','ok':True,'operation':'init','store':str(p)}
def normalize_scopes(role:str|None,extra:list[str])->list[str]:
 s=set(ROLES.get(role or '',set()))
 for x in extra:
  if x not in KNOWN_SCOPES: raise SecurityError(f'unknown scope: {x}')
  s.add(x)
 if not s: raise SecurityError('at least one role or scope is required')
 if '*' in s: s={'*'}
 return sorted(s)
def derive(secret:str,salt:bytes,rounds:int=PBKDF2_ROUNDS)->bytes:
 return hashlib.pbkdf2_hmac('sha256',secret.encode(),salt,rounds,dklen=32)
def issue(path:Path,role:str|None,extra:list[str],label:str|None)->dict[str,Any]:
 p=path.expanduser().resolve(); doc=load_store(p); token_id=secrets.token_hex(8); secret=secrets.token_urlsafe(32); salt=secrets.token_bytes(16); scopes=normalize_scopes(role,extra)
 doc['tokens'][token_id]={'schema':TOKEN_SCHEMA,'label':label or token_id,'role':role,'scopes':scopes,'salt':base64.b64encode(salt).decode(),'digest':base64.b64encode(derive(secret,salt)).decode(),'rounds':PBKDF2_ROUNDS,'created_at':now(),'revoked_at':None}
 atomic_json(p,doc)
 return {'schema':'ppc-lab-auth-result-v1','ok':True,'operation':'issue','token_id':token_id,'token':token_id+'.'+secret,'label':label or token_id,'role':role,'scopes':scopes}
def verify_token(path:Path,token:str,required:str|None=None)->dict[str,Any]:
 try: token_id,secret=token.split('.',1)
 except ValueError: return {'ok':False,'reason':'malformed-token'}
 try: doc=load_store(path)
 except (SecurityError,OSError,json.JSONDecodeError): return {'ok':False,'reason':'auth-store-error'}
 item=doc['tokens'].get(token_id)
 if not isinstance(item,dict): return {'ok':False,'reason':'unknown-token','token_id':token_id}
 if item.get('revoked_at'): return {'ok':False,'reason':'revoked','token_id':token_id}
 try:
  salt=base64.b64decode(item['salt'],validate=True); expected=base64.b64decode(item['digest'],validate=True); rounds=int(item.get('rounds',PBKDF2_ROUNDS))
 except Exception: return {'ok':False,'reason':'invalid-token-record','token_id':token_id}
 actual=derive(secret,salt,rounds)
 if not hmac.compare_digest(actual,expected): return {'ok':False,'reason':'invalid-secret','token_id':token_id}
 scopes=set(item.get('scopes',[])); allowed=required is None or '*' in scopes or required in scopes
 return {'ok':allowed,'authenticated':True,'authorized':allowed,'reason':'ok' if allowed else 'insufficient-scope','token_id':token_id,'label':item.get('label'),'role':item.get('role'),'scopes':sorted(scopes),'required':required}
def revoke(path:Path,token_id:str)->dict[str,Any]:
 p=path.expanduser().resolve(); doc=load_store(p); item=doc['tokens'].get(token_id)
 if not isinstance(item,dict): raise SecurityError(f'unknown token id: {token_id}')
 if not item.get('revoked_at'): item['revoked_at']=now(); atomic_json(p,doc)
 return {'schema':'ppc-lab-auth-result-v1','ok':True,'operation':'revoke','token_id':token_id,'revoked_at':item.get('revoked_at')}
def rotate(path:Path,token_id:str)->dict[str,Any]:
 p=path.expanduser().resolve(); doc=load_store(p); item=doc['tokens'].get(token_id)
 if not isinstance(item,dict): raise SecurityError(f'unknown token id: {token_id}')
 scopes=list(item.get('scopes',[])); label=str(item.get('label') or token_id); role=item.get('role'); revoke(p,token_id); result=issue(p,role,scopes,label)
 result['operation']='rotate'; result['replaces']=token_id; return result
def list_tokens(path:Path)->dict[str,Any]:
 doc=load_store(path); rows=[]
 for token_id,item in sorted(doc['tokens'].items()): rows.append({'token_id':token_id,'label':item.get('label'),'role':item.get('role'),'scopes':item.get('scopes',[]),'created_at':item.get('created_at'),'revoked_at':item.get('revoked_at')})
 return {'schema':'ppc-lab-auth-list-v1','security_api':API_VERSION,'count':len(rows),'tokens':rows}

def audit_append(path:Path,event:dict[str,Any])->dict[str,Any]:
 p=path.expanduser().resolve(); p.parent.mkdir(parents=True,exist_ok=True); prev='0'*64; seq=1
 if p.exists():
  lines=[x for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
  if lines:
   last=json.loads(lines[-1]); prev=str(last.get('record_hash','')); seq=int(last.get('seq',0))+1
 base={'schema':AUDIT_SCHEMA,'seq':seq,'timestamp':now(),'prev_hash':prev,**event}; digest=hashlib.sha256(canonical(base)).hexdigest(); base['record_hash']=digest
 with p.open('a',encoding='utf-8') as f: f.write(json.dumps(base,sort_keys=True,separators=(',',':'))+'\n'); f.flush(); os.fsync(f.fileno())
 return base
def audit_verify(path:Path)->dict[str,Any]:
 p=path.expanduser().resolve(); errors=[]; prev='0'*64; count=0
 if not p.exists(): return {'schema':'ppc-lab-audit-verify-v1','ok':True,'records':0,'errors':[]}
 for line_no,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
  if not line.strip(): continue
  count+=1
  try: rec=json.loads(line)
  except Exception as exc: errors.append(f'line {line_no}: invalid JSON: {exc}'); continue
  if rec.get('schema')!=AUDIT_SCHEMA: errors.append(f'line {line_no}: invalid schema')
  if rec.get('prev_hash')!=prev: errors.append(f'line {line_no}: previous hash mismatch')
  stored=rec.get('record_hash'); base=dict(rec); base.pop('record_hash',None); calc=hashlib.sha256(canonical(base)).hexdigest()
  if stored!=calc: errors.append(f'line {line_no}: record hash mismatch')
  prev=str(stored or '')
 return {'schema':'ppc-lab-audit-verify-v1','ok':not errors,'records':count,'head':prev,'errors':errors}

def main()->int:
 ap=argparse.ArgumentParser(prog='ppc-lab-security',description=__doc__); sub=ap.add_subparsers(dest='cmd',required=True)
 p=sub.add_parser('init'); p.add_argument('store',type=Path); p.add_argument('--force',action='store_true'); p.add_argument('--json',action='store_true')
 p=sub.add_parser('issue'); p.add_argument('store',type=Path); p.add_argument('--role',choices=sorted(ROLES)); p.add_argument('--scope',action='append',default=[]); p.add_argument('--label'); p.add_argument('--json',action='store_true')
 p=sub.add_parser('list'); p.add_argument('store',type=Path); p.add_argument('--json',action='store_true')
 p=sub.add_parser('verify'); p.add_argument('store',type=Path); p.add_argument('token'); p.add_argument('--require'); p.add_argument('--json',action='store_true')
 p=sub.add_parser('revoke'); p.add_argument('store',type=Path); p.add_argument('token_id'); p.add_argument('--json',action='store_true')
 p=sub.add_parser('rotate'); p.add_argument('store',type=Path); p.add_argument('token_id'); p.add_argument('--json',action='store_true')
 p=sub.add_parser('audit-verify'); p.add_argument('audit_log',type=Path); p.add_argument('--json',action='store_true')
 ns=ap.parse_args()
 try:
  if ns.cmd=='init': out=init_store(ns.store,ns.force)
  elif ns.cmd=='issue': out=issue(ns.store,ns.role,ns.scope,ns.label)
  elif ns.cmd=='list': out=list_tokens(ns.store)
  elif ns.cmd=='verify': out=verify_token(ns.store,ns.token,ns.require)
  elif ns.cmd=='revoke': out=revoke(ns.store,ns.token_id)
  elif ns.cmd=='rotate': out=rotate(ns.store,ns.token_id)
  else: out=audit_verify(ns.audit_log)
  if getattr(ns,'json',False): print(json.dumps(out,indent=2,sort_keys=True))
  else:
   if 'token' in out: print(out['token'])
   elif ns.cmd=='list':
    for x in out['tokens']: print(f"{x['token_id']} {x['label']} scopes={','.join(x['scopes'])} revoked={x['revoked_at'] or '-'}")
   else: print(f"{ns.cmd}={'PASS' if out.get('ok',False) else 'FAIL'}")
  return 0 if out.get('ok',True) else 1
 except (SecurityError,OSError,json.JSONDecodeError,ValueError) as exc:
  print(f'ppc-lab-security: {exc}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
