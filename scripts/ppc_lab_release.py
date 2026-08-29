#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic PPC Lab release manifest and source-archive tooling."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import importlib.util
import os
import re
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ppc-lab-release-manifest-v1"
API_VERSION = 1
EXCLUDE_DIRS = {".git", "build", "__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip", ".tar", ".gz", ".xz", ".7z"}

class ReleaseError(RuntimeError): pass

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def project_version(root: Path) -> str:
    text=(root/"CMakeLists.txt").read_text(encoding="utf-8")
    m=re.search(r"project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)",text)
    if not m: raise ReleaseError("cannot determine project version")
    return m.group(1)


def compatibility_snapshot(root: Path) -> dict[str, Any]:
    module_path=root/"scripts"/"ppc_lab_compat.py"
    if not module_path.is_file(): raise ReleaseError("missing scripts/ppc_lab_compat.py")
    spec=importlib.util.spec_from_file_location("ppclab_release_compat",module_path)
    if spec is None or spec.loader is None: raise ReleaseError("cannot load compatibility module")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.build_snapshot(root)

def source_files(root: Path, extra_exclude: set[Path] | None = None) -> list[Path]:
    root=root.resolve(); excluded={p.resolve() for p in (extra_exclude or set())}; out=[]
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink(): continue
        rel=p.relative_to(root)
        if rel.as_posix() == "RELEASE-MANIFEST.json": continue
        if any(part in EXCLUDE_DIRS for part in rel.parts): continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES: continue
        if p.resolve() in excluded: continue
        out.append(p)
    return sorted(out,key=lambda p:p.relative_to(root).as_posix())

def mode_for(path: Path) -> str:
    return "0755" if os.access(path,os.X_OK) else "0644"

def build_manifest(root: Path, *, extra_exclude: set[Path] | None = None) -> dict[str,Any]:
    files=source_files(root,extra_exclude)
    return {
        "schema":MANIFEST_SCHEMA,"release_api":API_VERSION,"version":project_version(root),
        "license":"GPL-3.0-only","cpp_api":1,"cpp_abi":1,"target_profile_api":1,
        "compatibility":compatibility_snapshot(root),
        "files":[{"path":p.relative_to(root).as_posix(),"size":p.stat().st_size,"mode":mode_for(p),"sha256":sha256_file(p)} for p in files],
    }

def write_manifest(path: Path, doc: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def verify(root: Path, manifest: dict[str,Any], manifest_path: Path | None = None) -> list[str]:
    errors=[]
    if manifest.get("schema")!=MANIFEST_SCHEMA: errors.append(f"schema must be {MANIFEST_SCHEMA}")
    try:
        if manifest.get("version")!=project_version(root): errors.append("manifest version does not match CMake project version")
    except (OSError,ReleaseError) as exc: errors.append(str(exc))
    listed={x.get("path"):x for x in manifest.get("files",[]) if isinstance(x,dict)}
    exclude={manifest_path} if manifest_path else set()
    actual={p.relative_to(root).as_posix():p for p in source_files(root,exclude)}
    for rel,p in actual.items():
        item=listed.get(rel)
        if item is None: errors.append(f"unlisted source file: {rel}"); continue
        if item.get("sha256")!=sha256_file(p): errors.append(f"hash mismatch: {rel}")
        if item.get("size")!=p.stat().st_size: errors.append(f"size mismatch: {rel}")
    for rel in sorted(set(listed)-set(actual)): errors.append(f"manifest references missing/excluded file: {rel}")
    return errors

def zip_time(epoch:int)->tuple[int,int,int,int,int,int]:
    epoch=max(epoch,315532800); d=dt.datetime.fromtimestamp(epoch,dt.timezone.utc)
    return d.year,d.month,d.day,d.hour,d.minute,d.second-d.second%2

def create_archive(root:Path,out:Path,epoch:int)->dict[str,Any]:
    root=root.resolve(); out=out.resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    tmp_manifest=out.parent/(out.name+".manifest.tmp.json")
    manifest=build_manifest(root,extra_exclude={out,tmp_manifest})
    files=source_files(root,{out,tmp_manifest}); ztime=zip_time(epoch)
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for p in files:
            rel=p.relative_to(root).as_posix(); info=zipfile.ZipInfo(rel,ztime); info.create_system=3
            mode=0o755 if os.access(p,os.X_OK) else 0o644; info.external_attr=(stat.S_IFREG|mode)<<16
            zf.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        payload=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode(); info=zipfile.ZipInfo("RELEASE-MANIFEST.json",ztime); info.create_system=3; info.external_attr=(stat.S_IFREG|0o644)<<16
        zf.writestr(info,payload,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    return manifest

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("manifest"); p.add_argument("root",type=Path); p.add_argument("--out",type=Path,required=True)
    p=sub.add_parser("verify"); p.add_argument("root",type=Path); p.add_argument("manifest",type=Path)
    p=sub.add_parser("archive"); p.add_argument("root",type=Path); p.add_argument("--out",type=Path,required=True); p.add_argument("--epoch",type=int,default=int(os.environ.get("SOURCE_DATE_EPOCH","946684800")))
    ns=ap.parse_args()
    try:
        root=ns.root.resolve()
        if ns.cmd=="manifest":
            out=ns.out.resolve(); doc=build_manifest(root,extra_exclude={out}); write_manifest(out,doc); print(f"{out} files={len(doc['files'])}"); return 0
        if ns.cmd=="verify":
            mp=ns.manifest.resolve(); doc=json.loads(mp.read_text(encoding="utf-8")); errors=verify(root,doc,mp if mp.is_relative_to(root) else None)
            if errors:
                for e in errors: print(f"ERROR: {e}",file=sys.stderr)
                return 1
            print(f"PASS: release manifest {doc['version']} files={len(doc['files'])}"); return 0
        manifest=create_archive(root,ns.out,ns.epoch); print(f"{ns.out.resolve()} sha256={sha256_file(ns.out.resolve())} files={len(manifest['files'])}"); return 0
    except (ReleaseError,OSError,json.JSONDecodeError,ValueError) as exc:
        print(f"ppc-lab-release: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
