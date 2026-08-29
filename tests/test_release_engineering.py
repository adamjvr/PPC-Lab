#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOL=ROOT/'scripts'/'ppc_lab_release.py'
PY=sys.executable

def run(*args:str):
    p=subprocess.run([PY,str(TOOL),*map(str,args)],text=True,capture_output=True)
    if p.returncode!=0:
        raise AssertionError(f"failed {args}:\nstdout={p.stdout}\nstderr={p.stderr}")
    return p

with tempfile.TemporaryDirectory(prefix='ppclab-release-') as raw:
    td=Path(raw); manifest=td/'manifest.json'
    run('manifest',ROOT,'--out',manifest)
    doc=json.loads(manifest.read_text())
    assert doc['schema']=='ppc-lab-release-manifest-v1' and doc['version']=='3.9.3'
    assert doc['compatibility']['schema']=='ppc-lab-compatibility-snapshot-v1' and doc['compatibility']['platform_version']=='3.9.3'
    assert doc['license']=='GPL-3.0-only' and doc['cpp_api']==1 and doc['cpp_abi']==1 and doc['target_profile_api']==1
    run('verify',ROOT,manifest)

    a=td/'a.zip'; b=td/'b.zip'
    run('archive',ROOT,'--out',a,'--epoch','946684800'); run('archive',ROOT,'--out',b,'--epoch','946684800')
    assert a.read_bytes()==b.read_bytes(), 'source archive is not reproducible'
    with zipfile.ZipFile(a) as zf:
        assert 'RELEASE-MANIFEST.json' in zf.namelist()
        embedded=json.loads(zf.read('RELEASE-MANIFEST.json'))
        assert embedded['version']=='3.9.3' and embedded['schema']=='ppc-lab-release-manifest-v1'
        assert embedded['compatibility']['platform_version']=='3.9.3'
        assert not any(x['path'].startswith(('build/','build-release/','build-asan/','build-debug/')) for x in embedded['files'])
        assert not any('/build/' in '/'+n or n.startswith('.git/') for n in zf.namelist())
        extract=td/'extract'; zf.extractall(extract)
    run('verify',extract,extract/'RELEASE-MANIFEST.json')
    assert hashlib.sha256(a.read_bytes()).digest()==hashlib.sha256(b.read_bytes()).digest()

print('PASS: deterministic source archive and release-manifest verification')
