#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CLI=Path(sys.argv[1]).resolve(); TOOL=ROOT/'scripts'/'ppc_lab_platform.py'
with tempfile.TemporaryDirectory(prefix="ppclab-v3-acceptance-") as raw:
    p=subprocess.run([sys.executable,str(TOOL),'acceptance','--core',str(CLI),'--tool-dir',str(ROOT/'scripts'),'--workspace',str(Path(raw)/'workspace'),'--json'],text=True,capture_output=True,check=False)
    assert p.returncode==0,(p.stdout,p.stderr)
    doc=json.loads(p.stdout); assert doc['schema']=='ppc-lab-acceptance-report-v1' and doc['ok'] is True
    by={x['stage']:x for x in doc['stages']}
    assert all(by[n]['ok'] for n in ('intake','exploration','evidence','hypothesis','knowledge'))
    assert by['hypothesis']['role']=='count-or-length' and by['hypothesis']['confidence']>=0.55
print('PASS: v3 synthetic intake-to-hypothesis mature-platform acceptance')
