#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Transactional PPC Lab source-release preflight, apply, rollback, and channel policy."""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, stat, sys, tempfile, zipfile
from pathlib import Path, PurePosixPath
from typing import Any

PLAN_SCHEMA='ppc-lab-upgrade-plan-v1'
TX_SCHEMA='ppc-lab-upgrade-transaction-v1'
CHANNEL_SCHEMA='ppc-lab-release-channel-v1'
RELEASE_SCHEMA='ppc-lab-release-manifest-v1'
API_VERSION=1
EXCLUDED_TOP={'.git','build','build-release','build-asan','__pycache__'}

class UpgradeError(RuntimeError): pass

def sha256_bytes(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def version_tuple(v:str)->tuple[int,int,int]:
    m=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:[-+].*)?',v)
    if not m: raise UpgradeError(f'invalid release version: {v}')
    return tuple(map(int,m.groups()))
def project_version(root:Path)->str:
    text=(root/'CMakeLists.txt').read_text(encoding='utf-8')
    m=re.search(r'project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)',text)
    if not m: raise UpgradeError('cannot determine current PPC Lab version')
    return m.group(1)
def safe_member(name:str)->Path:
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts: raise UpgradeError(f'unsafe archive member: {name}')
    return Path(*p.parts)
def release_doc(archive:Path)->tuple[dict[str,Any],dict[str,zipfile.ZipInfo]]:
    archive=archive.expanduser().resolve()
    try:
        with zipfile.ZipFile(archive,'r') as zf:
            infos={i.filename:i for i in zf.infolist()}
            if list(infos).count('RELEASE-MANIFEST.json')!=1: raise UpgradeError('release archive needs one RELEASE-MANIFEST.json')
            for name,info in infos.items():
                safe_member(name)
                mode=info.external_attr>>16
                if stat.S_IFMT(mode)==stat.S_IFLNK: raise UpgradeError(f'symlink member rejected: {name}')
            doc=json.loads(zf.read('RELEASE-MANIFEST.json').decode('utf-8'))
            if doc.get('schema')!=RELEASE_SCHEMA: raise UpgradeError(f'unsupported release schema: {doc.get("schema")}')
            expected={x.get('path'):x for x in doc.get('files',[]) if isinstance(x,dict)}
            actual=set(infos)-{'RELEASE-MANIFEST.json'}
            if actual!=set(expected):
                raise UpgradeError('release archive members do not match embedded manifest')
            for name in sorted(actual):
                data=zf.read(name); item=expected[name]
                if len(data)!=item.get('size') or sha256_bytes(data)!=item.get('sha256'):
                    raise UpgradeError(f'release member failed manifest verification: {name}')
            return doc,infos
    except (zipfile.BadZipFile,OSError,json.JSONDecodeError,KeyError) as exc:
        raise UpgradeError(f'cannot verify release archive: {exc}') from exc

def current_compat(root:Path)->dict[str,Any]:
    sys.path.insert(0,str((root/'scripts').resolve()))
    import ppc_lab_compat
    return ppc_lab_compat.build_snapshot(root)
def compat_errors(incoming:dict[str,Any], current:dict[str,Any])->list[str]:
    # Incoming must preserve the current same-major public surface.
    if incoming.get('schema')!='ppc-lab-compatibility-snapshot-v1': return ['incoming release has no supported compatibility declaration']
    errors=[]
    if incoming.get('platform_major')!=current.get('platform_major'): errors.append('platform major differs')
    for key in ('cpp_api','cpp_abi','target_profile_api','release_api','compatibility_api'):
        if incoming.get(key)!=current.get(key): errors.append(f'{key} differs current={current.get(key)} incoming={incoming.get(key)}')
    for field in ('schemas','installed_tools'):
        missing=sorted(set(current.get(field,[]))-set(incoming.get(field,[])))
        if missing: errors.append('incoming release removes stable '+field+': '+', '.join(missing))
    for key,val in current.get('persisted_formats',{}).items():
        inc=incoming.get('persisted_formats',{}).get(key)
        if inc is None or int(inc)<int(val): errors.append(f'incoming persisted format regresses {key}')
    return errors

def default_channels()->dict[str,Any]:
    return {'schema':CHANNEL_SCHEMA,'channel_api':API_VERSION,'default':'stable','channels':{
      'stable':{'major':3,'allow_prerelease':False,'allow_downgrade':False},
      'candidate':{'major':3,'allow_prerelease':True,'allow_downgrade':False},
      'pinned':{'major':3,'allow_prerelease':False,'allow_downgrade':False,'pin':None}}}
def load_channels(path:Path|None)->dict[str,Any]:
    if path is None: return default_channels()
    doc=json.loads(path.read_text(encoding='utf-8'))
    if doc.get('schema')!=CHANNEL_SCHEMA: raise UpgradeError(f'unsupported channel schema: {doc.get("schema")}')
    return doc
def channel_errors(channels:dict[str,Any], name:str, incoming_version:str, current_version:str)->list[str]:
    cfg=channels.get('channels',{}).get(name)
    if not isinstance(cfg,dict): return [f'unknown release channel: {name}']
    errors=[]; inc=version_tuple(incoming_version); cur=version_tuple(current_version)
    if inc[0]!=int(cfg.get('major',inc[0])): errors.append(f'channel {name} only permits major {cfg.get("major")}')
    prerelease=bool(re.search(r'[-+]',incoming_version))
    if prerelease and not cfg.get('allow_prerelease',False): errors.append(f'channel {name} rejects prereleases')
    if inc<cur and not cfg.get('allow_downgrade',False): errors.append(f'channel {name} rejects downgrade {current_version} -> {incoming_version}')
    pin=cfg.get('pin')
    if pin and incoming_version!=pin: errors.append(f'channel {name} is pinned to {pin}')
    return errors

def preflight(archive:Path,current_root:Path,channel_path:Path|None,channel:str)->dict[str,Any]:
    current_root=current_root.resolve(); doc,_=release_doc(archive); current_version=project_version(current_root)
    errors=[]; errors+=channel_errors(load_channels(channel_path),channel,doc['version'],current_version)
    errors+=compat_errors(doc.get('compatibility',{}),current_compat(current_root))
    return {'schema':PLAN_SCHEMA,'upgrade_api':API_VERSION,'ok':not errors,'current_version':current_version,
            'incoming_version':doc['version'],'archive':str(archive.resolve()),'archive_sha256':sha256_file(archive.resolve()),
            'channel':channel,'compatibility':doc.get('compatibility',{}),'errors':errors,
            'policy':{'target_binaries_copied':False,'git_metadata_preserved':True,'build_directories_preserved':True}}

def extract_verified(archive:Path,dest:Path)->dict[str,Any]:
    doc,_=release_doc(archive); dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive,'r') as zf:
        for info in zf.infolist():
            rel=safe_member(info.filename); q=dest/rel; q.parent.mkdir(parents=True,exist_ok=True); data=zf.read(info.filename); q.write_bytes(data)
            mode=(info.external_attr>>16)&0o777
            if mode: os.chmod(q,mode)
    return doc

def managed_files(root:Path)->set[Path]:
    out=set()
    for p in root.rglob('*'):
        if not p.is_file() or p.is_symlink(): continue
        rel=p.relative_to(root)
        if rel.parts and rel.parts[0] in EXCLUDED_TOP: continue
        if '__pycache__' in rel.parts or p.suffix in {'.pyc','.pyo'}: continue
        out.add(rel)
    return out

def snapshot_tree(root:Path,out:Path)->None:
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for rel in sorted(managed_files(root),key=lambda x:x.as_posix()):
            p=root/rel; info=zipfile.ZipInfo(rel.as_posix()); info.create_system=3; mode=stat.S_IMODE(p.stat().st_mode); info.external_attr=(stat.S_IFREG|mode)<<16
            zf.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)

def replace_from_dir(src:Path,dst:Path)->None:
    incoming=managed_files(src); current=managed_files(dst)
    # Remove obsolete managed files only; preserve .git/build/private outside source release.
    for rel in sorted(current-incoming,key=lambda x:len(x.parts),reverse=True):
        p=dst/rel
        try: p.unlink()
        except FileNotFoundError: pass
    for rel in sorted(incoming,key=lambda x:x.as_posix()):
        s=src/rel; d=dst/rel; d.parent.mkdir(parents=True,exist_ok=True)
        tmp=d.with_name(d.name+f'.upgrade-{os.getpid()}'); shutil.copy2(s,tmp); os.replace(tmp,d)
    for d in sorted((p for p in dst.rglob('*') if p.is_dir()),key=lambda x:len(x.parts),reverse=True):
        if d==dst or (d.relative_to(dst).parts and d.relative_to(dst).parts[0] in EXCLUDED_TOP): continue
        try: d.rmdir()
        except OSError: pass

def restore_snapshot(snapshot:Path,dst:Path)->None:
    with tempfile.TemporaryDirectory(prefix='ppclab-rollback-') as td:
        stage=Path(td); 
        with zipfile.ZipFile(snapshot,'r') as zf:
            for info in zf.infolist():
                rel=safe_member(info.filename); q=stage/rel; q.parent.mkdir(parents=True,exist_ok=True); q.write_bytes(zf.read(info.filename)); mode=(info.external_attr>>16)&0o777
                if mode: os.chmod(q,mode)
        replace_from_dir(stage,dst)

def apply_release(archive:Path,repo:Path,backup_dir:Path,channel_path:Path|None,channel:str)->dict[str,Any]:
    repo=repo.resolve(); plan=preflight(archive,repo,channel_path,channel)
    if not plan['ok']: raise UpgradeError('preflight failed: '+'; '.join(plan['errors']))
    backup_dir=backup_dir.resolve(); backup_dir.mkdir(parents=True,exist_ok=True)
    tx_id=f"{plan['current_version']}-to-{plan['incoming_version']}-{plan['archive_sha256'][:12]}"
    snapshot=backup_dir/f'{tx_id}.rollback.zip'; tx_path=backup_dir/f'{tx_id}.json'
    snapshot_tree(repo,snapshot)
    tx={'schema':TX_SCHEMA,'upgrade_api':API_VERSION,'transaction_id':tx_id,'status':'prepared','repo_root':str(repo),
        'from_version':plan['current_version'],'to_version':plan['incoming_version'],'archive':str(archive.resolve()),
        'archive_sha256':plan['archive_sha256'],'rollback_archive':str(snapshot),'rollback_sha256':sha256_file(snapshot),'channel':channel}
    tx_path.write_text(json.dumps(tx,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    try:
        with tempfile.TemporaryDirectory(prefix='ppclab-upgrade-') as td:
            stage=Path(td); extract_verified(archive,stage); replace_from_dir(stage,repo)
        if project_version(repo)!=plan['incoming_version']: raise UpgradeError('applied tree version mismatch')
        tx['status']='applied'; tx['result_version']=project_version(repo)
    except Exception:
        restore_snapshot(snapshot,repo); tx['status']='rolled-back-after-failure'; tx_path.write_text(json.dumps(tx,indent=2,sort_keys=True)+'\n'); raise
    tx_path.write_text(json.dumps(tx,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return {'schema':TX_SCHEMA,**tx,'transaction_path':str(tx_path),'ok':True}

def rollback(tx_path:Path,repo:Path|None)->dict[str,Any]:
    tx=json.loads(tx_path.read_text(encoding='utf-8'))
    if tx.get('schema')!=TX_SCHEMA: raise UpgradeError('unsupported transaction schema')
    dst=(repo or Path(tx['repo_root'])).resolve(); snap=Path(tx['rollback_archive']).resolve()
    if not snap.is_file() or sha256_file(snap)!=tx.get('rollback_sha256'): raise UpgradeError('rollback archive is missing or hash-mismatched')
    restore_snapshot(snap,dst); restored=project_version(dst)
    if restored!=tx.get('from_version'): raise UpgradeError(f'rollback restored unexpected version {restored}')
    tx['status']='rolled-back'; tx['rollback_result_version']=restored
    tx_path.write_text(json.dumps(tx,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return {'schema':TX_SCHEMA,**tx,'transaction_path':str(tx_path),'ok':True}

def emit(doc:dict[str,Any],as_json:bool)->None:
    if as_json: print(json.dumps(doc,indent=2,sort_keys=True))
    else:
        print(f"{doc.get('schema')} {'PASS' if doc.get('ok',True) else 'FAIL'}")
        if 'current_version' in doc: print(f"{doc['current_version']} -> {doc['incoming_version']} channel={doc['channel']}")
        for e in doc.get('errors',[]): print('ERROR: '+e,file=sys.stderr)

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('preflight'); p.add_argument('archive',type=Path); p.add_argument('--current-root',type=Path,default=Path('.')); p.add_argument('--channels',type=Path); p.add_argument('--channel',default='stable'); p.add_argument('--json',action='store_true')
    p=sub.add_parser('stage'); p.add_argument('archive',type=Path); p.add_argument('--out',type=Path,required=True); p.add_argument('--json',action='store_true')
    p=sub.add_parser('apply'); p.add_argument('archive',type=Path); p.add_argument('--repo-root',type=Path,default=Path('.')); p.add_argument('--backup-dir',type=Path,required=True); p.add_argument('--channels',type=Path); p.add_argument('--channel',default='stable'); p.add_argument('--json',action='store_true')
    p=sub.add_parser('rollback'); p.add_argument('transaction',type=Path); p.add_argument('--repo-root',type=Path); p.add_argument('--json',action='store_true')
    p=sub.add_parser('channel-init'); p.add_argument('path',type=Path); p.add_argument('--json',action='store_true')
    p=sub.add_parser('channel-check'); p.add_argument('path',type=Path); p.add_argument('archive',type=Path); p.add_argument('--current-root',type=Path,default=Path('.')); p.add_argument('--channel',default='stable'); p.add_argument('--json',action='store_true')
    ns=ap.parse_args()
    try:
        if ns.cmd=='preflight': doc=preflight(ns.archive,ns.current_root,ns.channels,ns.channel); emit(doc,ns.json); return 0 if doc['ok'] else 1
        if ns.cmd=='stage':
            out=ns.out.resolve();
            if out.exists() and any(out.iterdir()): raise UpgradeError('staging directory must be empty')
            rel=extract_verified(ns.archive,out); doc={'schema':PLAN_SCHEMA,'ok':True,'staged':str(out),'version':rel['version'],'archive_sha256':sha256_file(ns.archive.resolve())}; emit(doc,ns.json); return 0
        if ns.cmd=='apply': doc=apply_release(ns.archive,ns.repo_root,ns.backup_dir,ns.channels,ns.channel); emit(doc,ns.json); return 0
        if ns.cmd=='rollback': doc=rollback(ns.transaction,ns.repo_root); emit(doc,ns.json); return 0
        if ns.cmd=='channel-init':
            ns.path.parent.mkdir(parents=True,exist_ok=True); doc=default_channels(); ns.path.write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n'); emit({'schema':CHANNEL_SCHEMA,'ok':True,'path':str(ns.path)},ns.json); return 0
        doc=preflight(ns.archive,ns.current_root,ns.path,ns.channel); emit(doc,ns.json); return 0 if doc['ok'] else 1
    except (UpgradeError,OSError,ValueError,json.JSONDecodeError) as exc:
        print(f'ppc-lab-upgrade: {exc}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
