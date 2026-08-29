#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/'scripts'/'ppc_lab_support.py'
PLATFORM=ROOT/'scripts'/'ppc_lab_platform.py'
EVIDENCE=ROOT/'scripts'/'ppc_lab_evidence.py'
KNOWLEDGE=ROOT/'scripts'/'ppc_lab_knowledge.py'
CONTROL=ROOT/'scripts'/'ppc_lab_control.py'

def run(*args:str,check=True):
    p=subprocess.run([sys.executable,str(SUPPORT),*args],text=True,capture_output=True)
    if check and p.returncode!=0: raise AssertionError(p.stderr or p.stdout)
    return p

def tool(script:Path,*args:str):
    p=subprocess.run([sys.executable,str(script),*args],text=True,capture_output=True)
    if p.returncode!=0: raise AssertionError(p.stderr or p.stdout)
    return p

def main()->int:
    if len(sys.argv)!=2: raise SystemExit('usage: test_supportability.py /path/to/ppc-lab')
    core=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as td:
        d=Path(td); ev=d/'evidence'; kg=d/'knowledge'; cp=d/'control'
        tool(EVIDENCE,'init',str(ev)); tool(KNOWLEDGE,'init',str(kg),'--json'); tool(CONTROL,'init',str(cp))
        diag=json.loads(run('diagnose','--core',str(core),'--tool-dir',str(ROOT/'scripts'),'--evidence',str(ev),'--knowledge',str(kg),'--control',str(cp),'--json').stdout)
        assert diag['schema']=='ppc-lab-support-report-v1' and diag['healthy'] is True
        log=d/'worker.log'; log.write_text(f'authorization: Bearer SUPERSECRET\npassword=hunter2\npath={ev}\n',encoding='utf-8')
        bundle=d/'support.zip'
        b=json.loads(run('bundle','--core',str(core),'--tool-dir',str(ROOT/'scripts'),'--evidence',str(ev),'--knowledge',str(kg),'--control',str(cp),'--log',str(log),'--out',str(bundle),'--json').stdout)
        assert b['ok'] is True and bundle.is_file()
        with zipfile.ZipFile(bundle) as zf:
            names=set(zf.namelist()); assert names=={'support-report.json','SUPPORT-MANIFEST.json','logs/00-worker.log.txt'}
            text=zf.read('logs/00-worker.log.txt').decode(); assert 'SUPERSECRET' not in text and 'hunter2' not in text
            assert '<redacted>' in text and str(ev) not in text and '$EVIDENCE' in text
            manifest=json.loads(zf.read('SUPPORT-MANIFEST.json')); assert manifest['target_binaries_included'] is False
        assert json.loads(run('verify',str(bundle),'--json').stdout)['ok'] is True
        bad=d/'bad.zip'
        with zipfile.ZipFile(bad,'w') as zf:
            zf.writestr('target.elf',b'\x7fELF')
            zf.writestr('SUPPORT-MANIFEST.json','{}')
        assert run('verify',str(bad),check=False).returncode!=0
        binary=d/'binary.log'; binary.write_bytes(b'abc\x00def')
        assert run('bundle','--core',str(core),'--tool-dir',str(ROOT/'scripts'),'--out',str(d/'nope.zip'),'--log',str(binary),check=False).returncode==2
    print('supportability PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
