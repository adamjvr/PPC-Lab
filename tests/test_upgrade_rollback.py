#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import importlib.util, json, pathlib, shutil, subprocess, sys, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def main():
 up=load(ROOT/'scripts/ppc_lab_upgrade.py','up'); rel=load(ROOT/'scripts/ppc_lab_release.py','rel')
 with tempfile.TemporaryDirectory(prefix='ppclab-upgrade-test-') as td:
  t=pathlib.Path(td); current=t/'current'; incoming=t/'incoming'; backups=t/'backups'; current.mkdir(); incoming.mkdir()
  # Minimal release-shaped copies use the real tree so compatibility declarations remain genuine.
  for dst,ver in ((current,'3.8.0'),(incoming,'3.9.3')):
   for name in ('CMakeLists.txt','LICENSE'):
    shutil.copy2(ROOT/name,dst/name)
   for name in ('scripts','cmake','schemas'):
    shutil.copytree(ROOT/name,dst/name)
   txt=(dst/'CMakeLists.txt').read_text(); txt=txt.replace('VERSION 3.9.3','VERSION '+ver); (dst/'CMakeLists.txt').write_text(txt)
   # compatibility snapshot needs installed-tool declarations and the version template only; copied tree supplies both.
   (dst/'README.md').write_text('fixture\n'); (dst/'CHANGELOG.md').write_text(f'## {ver} — fixture\n')
  # Add a marker to prove apply/rollback actually switches files.
  (current/'marker.txt').write_text('old\n'); (incoming/'marker.txt').write_text('new\n')
  archive=t/'incoming.zip'; rel.create_archive(incoming,archive,946684800)
  plan=up.preflight(archive,current,None,'stable'); assert plan['ok'],plan
  tx=up.apply_release(archive,current,backups,None,'stable'); assert tx['ok']; assert (current/'marker.txt').read_text()=='new\n'; assert up.project_version(current)=='3.9.3'
  txp=pathlib.Path(tx['transaction_path']); rolled=up.rollback(txp,current); assert rolled['ok']; assert (current/'marker.txt').read_text()=='old\n'; assert up.project_version(current)=='3.8.0'
  # Downgrades on stable are rejected.
  old=t/'old'; shutil.copytree(current,old); old_archive=t/'old.zip'; rel.create_archive(old,old_archive,946684800)
  # Put current back at 3.9 for downgrade check.
  up.apply_release(archive,current,backups,None,'stable')
  bad=up.preflight(old_archive,current,None,'stable'); assert not bad['ok']; assert any('downgrade' in x for x in bad['errors'])
  # Tampering invalidates deterministic release intake.
  tampered=t/'tampered.zip'; shutil.copy2(archive,tampered)
  import zipfile
  with zipfile.ZipFile(tampered,'a') as zf: zf.writestr('UNLISTED.txt','x')
  try: up.release_doc(tampered); raise AssertionError('tampered release accepted')
  except up.UpgradeError: pass
 print('PASS: transactional source upgrade, stable channel, tamper rejection, and rollback')
 return 0
if __name__=='__main__': raise SystemExit(main())
