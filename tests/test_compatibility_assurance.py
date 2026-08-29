#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import importlib.util, json, sqlite3, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('compat',ROOT/'scripts/ppc_lab_compat.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def sqlite_store(root:Path,name:str,tables:list[str]):
    root.mkdir(parents=True); db=root/name
    with sqlite3.connect(db) as c:
        for t in tables: c.execute(f'CREATE TABLE {t}(key TEXT PRIMARY KEY, value TEXT)' if t=='meta' else f'CREATE TABLE {t}(id TEXT)')
        c.execute("INSERT INTO meta(key,value) VALUES('platform_format_version','1')"); c.execute("INSERT INTO meta(key,value) VALUES('schema_version','1')")

def main()->int:
    cur=mod.build_snapshot(ROOT); assert cur['platform_version']=='3.8.0'; assert cur['compatibility_api']==1
    assert 'ppc-lab-compat' in cur['installed_tools']; assert 'ppc-lab-compatibility-snapshot-v1.schema.json' in cur['schemas']
    base=json.loads((ROOT/'compat/baselines/v3.1.0.json').read_text()); assert mod.compare(cur,base)==[]
    broken=json.loads(json.dumps(base)); broken['cpp_abi']=99; broken['schemas'].append('never-existed-v1.schema.json')
    errs=mod.compare(cur,broken); assert any('cpp_abi changed' in x for x in errs); assert any('never-existed' in x for x in errs)
    with tempfile.TemporaryDirectory(prefix='ppclab-compat-') as td:
        td=Path(td); ev=td/'ev'; kg=td/'kg'; cp=td/'control'
        sqlite_store(ev,'evidence.sqlite3',['meta','artifacts','sources','inputs'])
        sqlite_store(kg,'knowledge.sqlite3',['meta','documents','nodes','edges'])
        cp.mkdir(); (cp/'control.json').write_text(json.dumps({'schema':'ppc-lab-control-v1','format_version':1})+'\n')
        audit=mod.audit_state(ev,kg,cp); assert audit['compatible'] is True and audit['migration_required'] is False
    print('PASS: LTS compatibility baseline, breaking-change detection, and persisted-state audit')
    return 0
if __name__=='__main__': raise SystemExit(main())
