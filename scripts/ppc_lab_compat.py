#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab LTS compatibility snapshots, baseline checks, and persisted-state audits."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from typing import Any

SCHEMA="ppc-lab-compatibility-snapshot-v1"
API_VERSION=1

class CompatError(RuntimeError): pass

def project_version(root:Path)->str:
    text=(root/'CMakeLists.txt').read_text(encoding='utf-8')
    m=re.search(r'project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)',text)
    if not m: raise CompatError('cannot determine project version')
    return m.group(1)

def macro_versions(root:Path)->dict[str,int]:
    text=(root/'cmake/Version.hpp.in').read_text(encoding='utf-8')
    out={}
    for key,macro in [('cpp_api','PPCLAB_CPP_API_VERSION'),('cpp_abi','PPCLAB_CPP_ABI_VERSION'),('target_profile_api','PPCLAB_TARGET_PROFILE_API_VERSION'),('release_api','PPCLAB_RELEASE_API_VERSION'),('compatibility_api','PPCLAB_COMPATIBILITY_API_VERSION'),('backup_api','PPCLAB_BACKUP_API_VERSION'),('observability_api','PPCLAB_OBSERVABILITY_API_VERSION'),('security_api','PPCLAB_SECURITY_API_VERSION'),('replication_api','PPCLAB_REPLICATION_API_VERSION')]:
        m=re.search(rf'#define {macro} ([0-9]+)',text)
        if not m: raise CompatError(f'missing public version macro {macro}')
        out[key]=int(m.group(1))
    return out

def schema_names(root:Path)->list[str]:
    return sorted(p.name for p in (root/'schemas').glob('*.schema.json') if p.is_file())

def installed_tools(root:Path)->list[str]:
    text=(root/'CMakeLists.txt').read_text(encoding='utf-8')
    names={'ppc-lab'}
    names.update(re.findall(r'RENAME\s+([A-Za-z0-9_.-]+)\)',text))
    # trace_intelligence.py is intentionally installed under its source name.
    if 'scripts/ppc_trace_intelligence.py' in text: names.add('ppc_trace_intelligence.py')
    return sorted(names)

def build_snapshot(root:Path)->dict[str,Any]:
    root=root.resolve(); version=project_version(root); apis=macro_versions(root)
    return {
      'schema':SCHEMA,'compatibility_api':API_VERSION,'platform_version':version,'platform_major':int(version.split('.')[0]),
      'license':'GPL-3.0-only', **apis,
      'schemas':schema_names(root),'installed_tools':installed_tools(root),
      'persisted_formats':{'evidence':1,'knowledge':1,'control':1,'replication':1},
      'policy':{'same_major_additive':True,'schema_removal_breaking':True,'api_abi_change_breaking':True,'persisted_format_downgrade_forbidden':True},
    }

def compare(current:dict[str,Any], baseline:dict[str,Any])->list[str]:
    errors=[]
    if baseline.get('schema')!=SCHEMA: errors.append(f'baseline schema must be {SCHEMA}')
    if int(current.get('platform_major',-1))!=int(baseline.get('platform_major',-2)): errors.append('platform major changed')
    for key in ('cpp_api','cpp_abi','target_profile_api','release_api','compatibility_api'):
        if int(current.get(key,-1))!=int(baseline.get(key,-2)): errors.append(f'{key} changed: baseline={baseline.get(key)} current={current.get(key)}')
    for field in ('schemas','installed_tools'):
        missing=sorted(set(baseline.get(field,[]))-set(current.get(field,[])))
        if missing: errors.append(f'missing stable {field}: '+', '.join(missing))
    for key,val in baseline.get('persisted_formats',{}).items():
        cur=current.get('persisted_formats',{}).get(key)
        if cur is None: errors.append(f'missing persisted format declaration: {key}')
        elif int(cur)<int(val): errors.append(f'persisted format downgraded: {key} baseline={val} current={cur}')
    return errors

def audit_state(evidence:Path|None, knowledge:Path|None, control:Path|None)->dict[str,Any]:
    scripts=Path(__file__).resolve().parent
    if str(scripts) not in sys.path: sys.path.insert(0,str(scripts))
    from ppc_lab_platform import upgrade_report
    report=upgrade_report(evidence,knowledge,control)
    return {'schema':'ppc-lab-compatibility-state-audit-v1','compatible':bool(report.get('compatible')),
            'migration_required':bool(report.get('migration_required')),'platform':report}

def dump(doc:dict[str,Any], path:Path|None=None)->None:
    text=json.dumps(doc,indent=2,sort_keys=True)+'\n'
    if path: path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text,encoding='utf-8')
    else: print(text,end='')

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('snapshot'); p.add_argument('root',type=Path,nargs='?',default=Path('.')); p.add_argument('--out',type=Path)
    p=sub.add_parser('check'); p.add_argument('baseline',type=Path); p.add_argument('--root',type=Path,default=Path('.')); p.add_argument('--json',action='store_true')
    p=sub.add_parser('state'); p.add_argument('--evidence',type=Path); p.add_argument('--knowledge',type=Path); p.add_argument('--control',type=Path); p.add_argument('--json',action='store_true')
    ns=ap.parse_args()
    try:
        if ns.cmd=='snapshot': dump(build_snapshot(ns.root),ns.out); return 0
        if ns.cmd=='check':
            cur=build_snapshot(ns.root); base=json.loads(ns.baseline.read_text(encoding='utf-8')); errors=compare(cur,base)
            doc={'schema':'ppc-lab-compatibility-check-v1','compatible':not errors,'current':cur,'baseline':base.get('platform_version'),'errors':errors}
            if ns.json: dump(doc)
            else:
                print(f"compatibility={'PASS' if not errors else 'FAIL'} current={cur['platform_version']} baseline={base.get('platform_version')}")
                for e in errors: print('ERROR: '+e,file=sys.stderr)
            return 0 if not errors else 1
        doc=audit_state(ns.evidence,ns.knowledge,ns.control)
        if ns.json: dump(doc)
        else: print(f"state compatibility={'PASS' if doc['compatible'] else 'FAIL'} migration_required={'yes' if doc['migration_required'] else 'no'}")
        return 0 if doc['compatible'] else 1
    except (OSError,ValueError,json.JSONDecodeError,CompatError) as exc:
        print(f'ppc-lab-compat: {exc}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
