#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; TOOL=ROOT/'scripts'/'ppc_lab_deploy.py'
def run(*args:str,check=True):
    p=subprocess.run([sys.executable,str(TOOL),*args],text=True,capture_output=True)
    if check and p.returncode!=0: raise AssertionError(p.stderr or p.stdout)
    return p
def main()->int:
    with tempfile.TemporaryDirectory(prefix='ppclab-deploy-') as td:
        stage=Path(td)/'root'
        plan=json.loads(run('plan','--service','both','--json').stdout)
        assert plan['schema']=='ppc-lab-deployment-v1' and plan['ppc_lab_version']=='3.8.0'
        assert plan['policy']['target_binaries_copied'] is False
        assert {f['path'] for f in plan['files']}=={'/etc/ppc-lab/ppc-lab.env','/etc/systemd/system/ppc-lab-api.service','/etc/systemd/system/ppc-lab-control.service'}
        report=json.loads(run('install','--service','both','--dest-root',str(stage),'--json').stdout); assert report['ok']
        manifest=stage/'etc/ppc-lab/deployment.json'; assert manifest.is_file()
        env=stage/'etc/ppc-lab/ppc-lab.env'; assert (env.stat().st_mode & 0o777)==0o600
        api=(stage/'etc/systemd/system/ppc-lab-api.service').read_text(); assert 'ProtectSystem=strict' in api and '--root /srv/ppc-lab/targets' in api
        assert json.loads(run('verify',str(manifest),'--dest-root',str(stage),'--json').stdout)['ok'] is True
        env.write_text(env.read_text()+'TAMPER=1\n'); bad=run('verify',str(manifest),'--dest-root',str(stage),'--json',check=False); assert bad.returncode==1
        # restore via install and prove ordinary uninstall preserves research state/private inputs
        run('install','--service','both','--dest-root',str(stage),'--json')
        state=stage/'var/lib/ppc-lab/evidence'; (state/'sentinel').write_text('keep')
        target=stage/'srv/ppc-lab/targets'; (target/'private.elf').write_bytes(b'private')
        doc=json.loads(manifest.read_text())
        out=json.loads(run('uninstall',str(manifest),'--dest-root',str(stage),'--json').stdout); assert out['ok']
        assert (state/'sentinel').is_file() and (target/'private.elf').is_file()
        # fresh install then explicit purge removes state/target roots
        run('install','--service','both','--dest-root',str(stage),'--json'); manifest=stage/'etc/ppc-lab/deployment.json'
        (stage/'srv/ppc-lab/targets'/'private.elf').write_bytes(b'private')
        out=json.loads(run('uninstall',str(manifest),'--dest-root',str(stage),'--purge-state','--json').stdout); assert out['ok']
        assert not (stage/'var/lib/ppc-lab').exists() and not (stage/'srv/ppc-lab/targets').exists()
        assert run('plan','--prefix','relative/path','--json',check=False).returncode==2
    print('deployment PASS'); return 0
if __name__=='__main__': raise SystemExit(main())
