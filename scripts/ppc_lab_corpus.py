#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Promote, replay, verify, bless, and minimize PPC Lab behavioral corpus cases."""
from __future__ import annotations
import argparse, copy, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from typing import Any

CORPUS_SCHEMA='ppc-lab-corpus-v1'; CASE_SCHEMA='ppc-lab-corpus-case-v1'; SUMMARY_SCHEMA='ppc-lab-corpus-replay-summary-v1'
ID_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')

class CorpusError(RuntimeError): pass

def sha256_file(p:Path)->str:
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def write_json(p:Path,v:Any): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def read_json(p:Path)->Any: return json.loads(p.read_text(encoding='utf-8'))
def engine_version(cli:Path)->str:
 r=subprocess.run([str(cli),'--version'],text=True,capture_output=True,check=False)
 if r.returncode: raise CorpusError(r.stderr.strip() or 'cannot query PPC Lab version')
 return r.stdout.strip().removeprefix('PPC Lab ').strip()

def init_corpus(root:Path):
 root.mkdir(parents=True,exist_ok=True); (root/'cases').mkdir(exist_ok=True); (root/'objects'/'sha256').mkdir(parents=True,exist_ok=True)
 m=root/'manifest.json'
 if not m.exists(): write_json(m,{'schema':CORPUS_SCHEMA,'format_version':1})
 elif read_json(m).get('schema')!=CORPUS_SCHEMA: raise CorpusError('corpus manifest schema mismatch')

def require_corpus(root:Path):
 m=root/'manifest.json'
 if not m.is_file(): raise CorpusError(f'corpus does not exist: {root}')
 if read_json(m).get('schema')!=CORPUS_SCHEMA: raise CorpusError('corpus manifest schema mismatch')

def contained(path:Path,root:Path)->Path|None:
 try:
  p=path.resolve(); p.relative_to(root.resolve()); return p
 except (ValueError,OSError): return None

def resolve_job_inputs(job:dict[str,Any],base:Path)->tuple[dict[str,Any],list[dict[str,Any]],list[Path]]:
 j=copy.deepcopy(job); specs=[]; paths=[]
 for field in ('path','data_path'):
  if field not in j.get('image',{}): continue
  raw=j['image'][field]; p=Path(raw); p=(base/p if not p.is_absolute() else p).resolve()
  if not p.is_file(): raise CorpusError(f'image.{field} missing: {p}')
  idx=len(specs); token=f'$INPUT:{idx}'; j['image'][field]=token
  specs.append({'field':f'image.{field}','sha256':sha256_file(p),'size':p.stat().st_size,'path_hint':Path(raw).name if Path(raw).is_absolute() else str(Path(raw))})
  paths.append(p)
 return j,specs,paths

def stage_job(job:dict[str,Any], paths:list[Path], td:Path)->dict[str,Any]:
 j=copy.deepcopy(job); inp=td/'inputs'; inp.mkdir(parents=True,exist_ok=True)
 for i,p in enumerate(paths):
  dst=inp/f'{i:02d}-{p.name}'; shutil.copyfile(p,dst)
  token=f'$INPUT:{i}'
  for field in ('path','data_path'):
   if j.get('image',{}).get(field)==token: j['image'][field]=str(dst.relative_to(td))
 return j

def run_worker(job:dict[str,Any],paths:list[Path],cli:Path,worker:Path,timeout:float)->dict[str,Any]:
 with tempfile.TemporaryDirectory(prefix='ppclab-corpus-') as s:
  td=Path(s); staged=stage_job(job,paths,td); jp=td/'job.json'; write_json(jp,staged)
  r=subprocess.run([sys.executable,str(worker),'--ppc-lab',str(cli),'--root',str(td),'run',str(jp)],text=True,capture_output=True,timeout=timeout,check=False)
  try:return json.loads(r.stdout)
  except Exception as e: raise CorpusError(f'worker returned invalid JSON: {r.stdout[:200]} {r.stderr[:200]}') from e

def stable_expectation(r:dict[str,Any])->dict[str,Any]:
 e={'ok':r.get('ok'),'exit_code':r.get('exit_code'),'timed_out':r.get('timed_out',False)}
 res=r.get('result')
 if isinstance(res,dict):
  x={k:copy.deepcopy(res[k]) for k in ('stop_reason','instructions','pc','instruction','registers','lr','ctr','cr') if k in res}
  if 'dumps' in res:x['dumps']=[{k:d[k] for k in ('address','size','fnv1a64') if k in d} for d in res['dumps']]
  e['result']=x
 snap=r.get('snapshot')
 if isinstance(snap,dict):
  x={k:copy.deepcopy(snap[k]) for k in ('stop_reason','instructions','pc','instruction','cpu','symbols') if k in snap}
  if 'regions' in snap:x['regions']=[{k:d[k] for k in ('name','base','size','perms','fnv1a64') if k in d} for d in snap['regions']]
  if 'dumps' in snap:x['dumps']=[{k:d[k] for k in ('address','size','fnv1a64') if k in d} for d in snap['dumps']]
  e['snapshot']=x
 if r.get('error') is not None:e['error']=r['error']
 return e

def diffs(exp:Any,got:Any,path='$')->list[dict[str,Any]]:
 out=[]
 if isinstance(exp,dict):
  if not isinstance(got,dict): return [{'path':path,'expected':exp,'actual':got}]
  for k,v in exp.items(): out+=diffs(v,got.get(k,'<missing>'),path+'.'+k)
 elif isinstance(exp,list):
  if not isinstance(got,list) or len(exp)!=len(got): return [{'path':path,'expected':exp,'actual':got}]
  for i,v in enumerate(exp): out+=diffs(v,got[i],f'{path}[{i}]')
 elif exp!=got: out.append({'path':path,'expected':exp,'actual':got})
 return out

def find_inputs(case:dict[str,Any],corpus:Path,input_roots:list[Path],maps:dict[str,Path])->list[Path]:
 found=[]; index=None
 for spec in case['inputs']:
  h=spec['sha256']; emb=spec.get('embedded')
  candidates=[]
  if h in maps:candidates.append(maps[h])
  if emb:
   ep=contained(corpus/emb,corpus)
   if ep is None: raise CorpusError('embedded input path escapes corpus root')
   candidates.append(ep)
  for root in input_roots:
   hint=Path(spec.get('path_hint',''))
   if hint and not hint.is_absolute():
    hp=contained(root/hint,root)
    if hp is not None: candidates.append(hp)
  p=next((x.resolve() for x in candidates if x.is_file() and x.stat().st_size==spec['size'] and sha256_file(x)==h),None)
  if p is None:
   if index is None:
    index={}
    for root in input_roots:
     rr=root.resolve()
     for x in root.rglob('*'):
      if not x.is_file(): continue
      xr=contained(x,rr)
      if xr is not None: index.setdefault(xr.stat().st_size,[]).append(xr)
   for x in index.get(spec['size'],[]):
    if sha256_file(x)==h: p=x.resolve(); break
  if p is None: raise CorpusError(f'missing input sha256={h} hint={spec.get("path_hint","")}')
  found.append(p)
 return found

def load_case(corpus:Path,cid:str)->tuple[Path,dict[str,Any]]:
 p=corpus/'cases'/f'{cid}.json'
 if not p.is_file(): raise CorpusError(f'case not found: {cid}')
 c=read_json(p)
 if c.get('schema')!=CASE_SCHEMA: raise CorpusError(f'case schema mismatch: {cid}')
 return p,c

def parse_maps(values:list[str])->dict[str,Path]:
 d={}
 for v in values:
  if '=' not in v: raise CorpusError('--input must be SHA256=PATH')
  h,p=v.split('=',1); d[h.lower()]=Path(p).resolve()
 return d

def selected_cases(corpus:Path,ids:list[str],tags:list[str]):
 files=[corpus/'cases'/f'{x}.json' for x in ids] if ids else sorted((corpus/'cases').glob('*.json'))
 out=[]
 for p in files:
  if not p.is_file(): raise CorpusError(f'case not found: {p.stem}')
  c=read_json(p)
  if tags and not set(tags).issubset(set(c.get('tags',[]))): continue
  out.append((p,c))
 return out

def do_replay(case:dict[str,Any],corpus:Path,cli:Path,worker:Path,input_roots:list[Path],maps:dict[str,Path],timeout:float,backend:str|None=None):
 paths=find_inputs(case,corpus,input_roots,maps); job=copy.deepcopy(case['job'])
 if backend: job.setdefault('execution',{})['backend']=backend
 r=run_worker(job,paths,cli,worker,timeout); e=case['expectation']; ds=diffs(e,stable_expectation(r)); return r,ds

def main()->int:
 ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--ppc-lab',default='ppc-lab'); ap.add_argument('--worker',default='ppc-lab-worker'); ap.add_argument('--timeout',type=float,default=30.0)
 sp=ap.add_subparsers(dest='cmd',required=True)
 p=sp.add_parser('init');p.add_argument('corpus',type=Path)
 p=sp.add_parser('promote');p.add_argument('corpus',type=Path);p.add_argument('--id',required=True);p.add_argument('--job',type=Path,required=True);p.add_argument('--description',default='');p.add_argument('--tag',action='append',default=[]);p.add_argument('--embed-input',action='store_true');p.add_argument('--allow-failed-baseline',action='store_true')
 p=sp.add_parser('list');p.add_argument('corpus',type=Path)
 p=sp.add_parser('verify');p.add_argument('corpus',type=Path)
 p=sp.add_parser('replay');p.add_argument('corpus',type=Path);p.add_argument('--case',action='append',default=[]);p.add_argument('--tag',action='append',default=[]);p.add_argument('--input-root',type=Path,action='append',default=[]);p.add_argument('--input',action='append',default=[]);p.add_argument('--backend',choices=['auto','builtin','unicorn']);p.add_argument('--json',type=Path);p.add_argument('--fail-fast',action='store_true')
 p=sp.add_parser('bless');p.add_argument('corpus',type=Path);p.add_argument('case');p.add_argument('--input-root',type=Path,action='append',default=[]);p.add_argument('--input',action='append',default=[]);p.add_argument('--backend',choices=['auto','builtin','unicorn']);p.add_argument('--yes',action='store_true')
 p=sp.add_parser('minimize');p.add_argument('corpus',type=Path);p.add_argument('case');p.add_argument('--input-root',type=Path,action='append',default=[]);p.add_argument('--input',action='append',default=[]);p.add_argument('--output',type=Path,required=True)
 ns=ap.parse_args(); cli=Path(shutil.which(ns.ppc_lab) or ns.ppc_lab).resolve(); worker=Path(shutil.which(ns.worker) or ns.worker).resolve()
 try:
  if ns.cmd=='init': init_corpus(ns.corpus); print(f'initialized {ns.corpus}'); return 0
  if ns.cmd=='promote':
   init_corpus(ns.corpus)
   if not ID_RE.match(ns.id): raise CorpusError('invalid case id')
   job=read_json(ns.job); norm,specs,paths=resolve_job_inputs(job,ns.job.parent.resolve()); r=run_worker(norm,paths,cli,worker,ns.timeout)
   if not r.get('ok') and not ns.allow_failed_baseline: raise CorpusError('baseline execution failed; use --allow-failed-baseline to promote intentionally')
   for i,(spec,path) in enumerate(zip(specs,paths)):
    if ns.embed_input:
     rel=Path('objects')/'sha256'/spec['sha256']; dst=ns.corpus/rel; dst.parent.mkdir(parents=True,exist_ok=True)
     if not dst.exists(): shutil.copyfile(path,dst)
     spec['embedded']=rel.as_posix()
   case={'schema':CASE_SCHEMA,'id':ns.id,'description':ns.description,'tags':sorted(set(ns.tag)),'created_with':{'ppc_lab':engine_version(cli)},'inputs':specs,'job':norm,'expectation':stable_expectation(r)}
   write_json(ns.corpus/'cases'/f'{ns.id}.json',case); print(f'promoted {ns.id}'); return 0
  require_corpus(ns.corpus)
  if ns.cmd=='list':
   for p,c in selected_cases(ns.corpus,[],[]): print(f"{c.get('id',p.stem)}\t{','.join(c.get('tags',[]))}\t{c.get('description','')}")
   return 0
  if ns.cmd=='verify':
   ids=set(); n=0
   for p,c in selected_cases(ns.corpus,[],[]):
    if c.get('schema')!=CASE_SCHEMA: raise CorpusError(f'{p}: bad schema')
    cid=c.get('id');
    if not isinstance(cid,str) or not ID_RE.match(cid): raise CorpusError(f'{p}: invalid id')
    if cid in ids: raise CorpusError(f'duplicate id: {cid}')
    ids.add(cid)
    for spec in c.get('inputs',[]):
     if not re.fullmatch(r'[0-9a-f]{64}',spec.get('sha256','')): raise CorpusError(f'{cid}: invalid input sha256')
     if spec.get('embedded'):
      x=contained(ns.corpus/spec['embedded'],ns.corpus)
      if x is None: raise CorpusError(f'{cid}: embedded input path escapes corpus root')
      if not x.is_file() or x.stat().st_size!=spec['size'] or sha256_file(x)!=spec['sha256']: raise CorpusError(f'{cid}: corrupt embedded input')
    n+=1
   print(f'PASS: {n} corpus cases verified'); return 0
  maps=parse_maps(ns.input); roots=[p.resolve() for p in ns.input_root]
  if ns.cmd=='replay':
   rows=[]; fail=0
   for p,c in selected_cases(ns.corpus,ns.case,ns.tag):
    r,ds=do_replay(c,ns.corpus,cli,worker,roots,maps,ns.timeout,ns.backend); ok=not ds; fail+=not ok
    rows.append({'id':c['id'],'ok':ok,'differences':ds,'engine_version':engine_version(cli)})
    print(('PASS' if ok else 'FAIL')+f" {c['id']}" + ('' if ok else f' ({len(ds)} differences)'))
    if ds:
     for d in ds[:10]: print(f"  {d['path']}: expected={d['expected']!r} actual={d['actual']!r}")
    if fail and ns.fail_fast: break
   summary={'schema':SUMMARY_SCHEMA,'engine_version':engine_version(cli),'cases':len(rows),'passed':len(rows)-fail,'failed':fail,'results':rows}
   if ns.json: write_json(ns.json,summary)
   return 1 if fail else 0
  p,c=load_case(ns.corpus,ns.case)
  if ns.cmd=='bless':
   if not ns.yes: raise CorpusError('bless requires --yes')
   r,ds=do_replay(c,ns.corpus,cli,worker,roots,maps,ns.timeout,ns.backend); c['expectation']=stable_expectation(r); c['blessed_with']={'ppc_lab':engine_version(cli)}; write_json(p,c); print(f'blessed {c["id"]} ({len(ds)} previous differences)'); return 0
  if ns.cmd=='minimize':
   paths=find_inputs(c,ns.corpus,roots,maps); base=copy.deepcopy(c['job']); r=run_worker(base,paths,cli,worker,ns.timeout); base_d=diffs(c['expectation'],stable_expectation(r))
   if not base_d: raise CorpusError('case currently passes; nothing to minimize')
   wanted={d['path'] for d in base_d}; job=copy.deepcopy(base); removed=[]
   for field in ('registers','float_registers','writes_u32','writes_f32','syscall_returns','bindings'):
    for key in list(job.get(field,{}).keys()):
     cand=copy.deepcopy(job); del cand[field][key]
     rr=run_worker(cand,paths,cli,worker,ns.timeout); dd=diffs(c['expectation'],stable_expectation(rr))
     if wanted & {d['path'] for d in dd}: job=cand; removed.append(f'{field}.{key}')
   out=copy.deepcopy(c); out['id']=c['id']+'-minimized'; out['job']=job; out['minimized_from']=c['id']; out['minimized_removed']=removed; write_json(ns.output,out); print(f'minimized {c["id"]}: removed {len(removed)} setup entries'); return 0
  raise CorpusError('unsupported command')
 except (CorpusError,subprocess.TimeoutExpired,json.JSONDecodeError) as e:
  print(f'ERROR: {e}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
