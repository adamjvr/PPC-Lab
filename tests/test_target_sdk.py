#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'scripts'/'ppc_lab_target.py'
PY=sys.executable

def run(*args:str):
    p=subprocess.run([PY,str(TOOL),*map(str,args)],text=True,capture_output=True)
    if p.returncode!=0:
        raise AssertionError(f"failed {args}:\nstdout={p.stdout}\nstderr={p.stderr}")
    return p

def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix='ppclab-target-sdk-') as raw:
    td=Path(raw); profile=td/'my-device'
    run('init',profile,'--id','my-device','--name','My Device','--description','Synthetic profile')
    doc=json.loads((profile/'profile.json').read_text())
    assert doc['schema']=='ppc-lab-target-profile-v1' and doc['profile_api']==1
    assert doc['inputs'][0]['redistributable'] is False
    p=run('validate',profile,'--json'); status=json.loads(p.stdout); assert status['ok'] is True
    p=run('inspect',profile,'--json'); info=json.loads(p.stdout); assert info['id']=='my-device' and info['ok'] is True

    a=td/'a.zip'; b=td/'b.zip'
    run('pack',profile,'--out',a,'--epoch','946684800'); run('pack',profile,'--out',b,'--epoch','946684800')
    assert a.read_bytes()==b.read_bytes(), 'profile packaging is not reproducible'
    with zipfile.ZipFile(a) as zf:
        names=zf.namelist(); assert 'my-device/profile.json' in names and 'my-device/PROFILE-PACKAGE.json' in names
        package=json.loads(zf.read('my-device/PROFILE-PACKAGE.json'))
        assert package['schema']=='ppc-lab-target-profile-package-v1' and package['id']=='my-device'
        assert all(not n.endswith('.bin') for n in names)

    # Undeclared binary-like target bytes are rejected from public profile packages.
    (profile/'private.bin').write_bytes(b'private target bytes')
    bad=subprocess.run([PY,str(TOOL),'validate',str(profile)],text=True,capture_output=True)
    assert bad.returncode==1 and 'not declared redistributable' in bad.stderr
    (profile/'private.bin').unlink()
    assert sha(a)==sha(b)

print('PASS: target-profile SDK validation and reproducible packaging')
