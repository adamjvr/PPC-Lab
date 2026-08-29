#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import hashlib, json, os, sqlite3, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BACKUP=ROOT/'scripts/ppc_lab_backup.py'
EVIDENCE=ROOT/'scripts/ppc_lab_evidence.py'
KNOWLEDGE=ROOT/'scripts/ppc_lab_knowledge.py'
CONTROL=ROOT/'scripts/ppc_lab_control.py'
DEPLOY=ROOT/'scripts/ppc_lab_deploy.py'

def run(tool,*args,check=True):
    p=subprocess.run([sys.executable,str(tool),*map(str,args)],text=True,capture_output=True)
    if check and p.returncode:
        raise AssertionError(f"failed {tool.name}: {p.stderr}\n{p.stdout}")
    return p

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    with tempfile.TemporaryDirectory(prefix='ppclab-backup-test-') as td:
        t=Path(td); state=t/'state'; evidence=state/'evidence'; knowledge=state/'knowledge'; control=state/'control'
        run(EVIDENCE,'init',evidence)
        doc=t/'artifact.json'; doc.write_text(json.dumps({'schema':'ppc-lab-result-v1','backend':'builtin','stop_reason':'returned','instructions':7,'pc':'0x10000004','inputs':[{'path':'private.elf','sha256':'a'*64,'size':123}]})+'\n')
        run(EVIDENCE,'ingest',evidence,doc,'--json')
        run(KNOWLEDGE,'init',knowledge)
        run(KNOWLEDGE,'ingest',knowledge,doc,'--json')
        run(CONTROL,'init',control)
        (control/'history'/'history.ndjson').write_text(json.dumps({'schema':'ppc-lab-control-history-record-v1','id':'old-run','status':'complete'})+'\n')
        # Transient/private-like files must not enter the backup.
        (control/'telemetry.json').write_text('{"secret":"transient"}\n')
        (control/'SERVER.lock').write_text(json.dumps({'pid':99999999})+'\n')
        (control/'runs'/'case').mkdir(parents=True); (control/'runs'/'case'/'summary.json').write_text('{"schema":"ppc-lab-scheduler-summary-v1"}\n')
        (control/'runs'/'case'/'should-not-copy.bin').write_bytes(b'PRIVATE-TARGET-BYTES')
        deployment=t/'deployment.json'
        plan=json.loads(run(DEPLOY,'plan','--json').stdout); deployment.write_text(json.dumps(plan)+'\n')
        archive=t/'backup.zip'
        created=json.loads(run(BACKUP,'create','--root',ROOT,'--state-root',state,'--deployment',deployment,'--out',archive,'--json').stdout)
        assert created['ok'] and created['manifest']['ppc_lab_version']=='3.5.0'
        assert created['manifest']['policy']['target_binaries_copied'] is False
        with zipfile.ZipFile(archive) as z:
            names=set(z.namelist()); blob=b''.join(z.read(n) for n in names)
        assert 'state/evidence/evidence.sqlite3' in names and 'state/knowledge/knowledge.sqlite3' in names
        assert 'state/control/control.json' in names and 'metadata/deployment.json' in names
        assert not any('SERVER.lock' in n or 'telemetry.json' in n or n.endswith('.bin') for n in names)
        assert b'PRIVATE-TARGET-BYTES' not in blob
        verified=json.loads(run(BACKUP,'verify',archive,'--json').stdout); assert verified['ok']
        inspected=json.loads(run(BACKUP,'inspect',archive,'--json').stdout); assert inspected['ok'] and inspected['manifest']['components']==['evidence','knowledge','control']
        restored=t/'restored'
        out=json.loads(run(BACKUP,'restore',archive,'--state-root',restored,'--json').stdout); assert out['ok'] and set(out['components'])=={'evidence','knowledge','control'}
        assert (restored/'control/history/history.ndjson').is_file()
        for db in [restored/'evidence/evidence.sqlite3', restored/'knowledge/knowledge.sqlite3']:
            with sqlite3.connect(db) as c: assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        # Refuse overwrite by default; force creates a safety copy of previous state.
        assert run(BACKUP,'restore',archive,'--state-root',restored,check=False).returncode==2
        (restored/'control'/'marker.json').write_text('{}\n')
        forced=json.loads(run(BACKUP,'restore',archive,'--state-root',restored,'--force','--json').stdout)
        assert forced['ok'] and forced['pre_restore'] and Path(forced['pre_restore']).is_dir()
        assert (Path(forced['pre_restore'])/'control/marker.json').is_file()
        # Active control plane is rejected unless explicitly overridden.
        lock=control/'SERVER.lock'; lock.write_text(json.dumps({'pid':os.getpid()})+'\n')
        assert run(BACKUP,'create','--root',ROOT,'--state-root',state,'--out',t/'active.zip',check=False).returncode==2
        live=json.loads(run(BACKUP,'create','--root',ROOT,'--state-root',state,'--out',t/'live.zip','--allow-live-control','--json').stdout)
        assert live['ok'] and live['manifest']['policy']['control_live_snapshot'] is True
        # Extra archive member is rejected even when the original manifest remains valid.
        bad=t/'bad.zip'
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad,'w',compression=zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist(): dst.writestr(info,src.read(info.filename))
            dst.writestr('state/control/evil.bin',b'evil')
        badcheck=json.loads(run(BACKUP,'verify',bad,'--json',check=False).stdout)
        assert badcheck['ok'] is False and run(BACKUP,'verify',bad,check=False).returncode==1
    print('backup/restore PASS'); return 0
if __name__=='__main__': raise SystemExit(main())
