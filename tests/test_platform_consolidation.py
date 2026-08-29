#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CLI=Path(sys.argv[1]).resolve()
PLATFORM=ROOT/'scripts'/'ppc_lab_platform.py'
EVIDENCE=ROOT/'scripts'/'ppc_lab_evidence.py'
KNOWLEDGE=ROOT/'scripts'/'ppc_lab_knowledge.py'
CONTROL=ROOT/'scripts'/'ppc_lab_control.py'
PY=sys.executable


def run(tool:Path,*args:str):
    return subprocess.run([PY,str(tool),*map(str,args)],text=True,capture_output=True,check=False)

def platform(*args:str): return run(PLATFORM,*args)

with tempfile.TemporaryDirectory(prefix='ppclab-v3-platform-') as raw:
    td=Path(raw); evidence=td/'evidence'; knowledge=td/'knowledge'; control=td/'control'
    assert run(EVIDENCE,'init',evidence).returncode==0
    assert run(KNOWLEDGE,'init',knowledge,'--json').returncode==0
    assert run(CONTROL,'init',control).returncode==0

    p=platform('upgrade-check','--evidence',evidence,'--knowledge',knowledge,'--control',control,'--json')
    assert p.returncode==0,(p.stdout,p.stderr); pre=json.loads(p.stdout)
    assert pre['schema']=='ppc-lab-upgrade-report-v1' and pre['compatible'] is True and pre['migration_required'] is True

    p=platform('migrate','--evidence',evidence,'--knowledge',knowledge,'--control',control,'--yes','--json')
    assert p.returncode==0,(p.stdout,p.stderr); migrated=json.loads(p.stdout)
    assert migrated['postcheck']['compatible'] is True and migrated['postcheck']['migration_required'] is False
    assert (evidence/'evidence.sqlite3.pre-v3.0.0.bak').is_file()
    assert (knowledge/'knowledge.sqlite3.pre-v3.0.0.bak').is_file()
    assert (control/'control.json.pre-v3.0.0.bak').is_file()

    # Migration is idempotent and preserves the first safety backup.
    p2=platform('migrate','--evidence',evidence,'--knowledge',knowledge,'--control',control,'--yes','--json')
    assert p2.returncode==0,(p2.stdout,p2.stderr)
    again=json.loads(p2.stdout); assert all(not x['changed'] for x in again['components'].values())

    p=platform('status','--core',CLI,'--tool-dir',ROOT/'scripts','--json')
    assert p.returncode==0,(p.stdout,p.stderr); status=json.loads(p.stdout)
    assert status['schema']=='ppc-lab-platform-status-v1' and status['ready'] is True
    assert status['core']['version']=='3.8.0' and status['companions']['hypothesize']['available'] is True

    p=platform('doctor','--core',CLI,'--tool-dir',ROOT/'scripts','--evidence',evidence,'--knowledge',knowledge,'--control',control,'--json')
    assert p.returncode==0,(p.stdout,p.stderr); doctor=json.loads(p.stdout)
    assert doctor['ready'] is True and doctor['core_doctor']['ok'] is True


print('PASS: v3 platform status and persisted-state migration')
