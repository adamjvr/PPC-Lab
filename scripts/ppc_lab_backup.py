#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Create, verify, inspect, and restore PPC Lab LTS disaster-recovery backups.

Backups contain PPC Lab persistent research state only: evidence, knowledge, and
control-plane state. Private target-input roots, deployment secrets, caches,
and arbitrary files are never copied.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

BACKUP_SCHEMA = "ppc-lab-backup-v1"
REPORT_SCHEMA = "ppc-lab-backup-report-v1"
API_VERSION = 1
ALLOWED_COMPONENTS = ("evidence", "knowledge", "control")
TRANSIENT_CONTROL = {"SERVER.lock", "telemetry.json", "PAUSE", "DRAIN", "CANCEL"}
CONTROL_SUFFIXES = {".json", ".ndjson", ".log", ".txt"}

class BackupError(RuntimeError):
    pass

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()

def project_version(root: Path) -> str:
    import re
    text=(root/"CMakeLists.txt").read_text(encoding="utf-8")
    m=re.search(r"project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)", text)
    if not m: raise BackupError("cannot determine PPC Lab version")
    return m.group(1)

def safe_member(name: str) -> PurePosixPath:
    p=PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise BackupError(f"unsafe backup member: {name}")
    return p

def regular_files(root: Path, *, component: str) -> list[Path]:
    if not root.exists(): return []
    if root.is_symlink(): raise BackupError(f"{component} root must not be a symlink: {root}")
    out=[]
    for p in sorted(root.rglob("*")):
        if p.is_symlink(): raise BackupError(f"symlink not permitted in {component} state: {p}")
        if not p.is_file(): continue
        rel=p.relative_to(root)
        if component == "control":
            if rel.as_posix() in TRANSIENT_CONTROL or p.name in TRANSIENT_CONTROL: continue
            if p.suffix.lower() not in CONTROL_SUFFIXES: continue
        out.append(p)
    return out

def sqlite_snapshot(src: Path, dst: Path) -> None:
    if not src.is_file(): raise BackupError(f"missing SQLite state: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, sqlite3.connect(dst) as target:
            source.backup(target)
            row=target.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok": raise BackupError(f"SQLite integrity check failed after snapshot: {src}")
    except sqlite3.Error as exc:
        raise BackupError(f"cannot snapshot SQLite state {src}: {exc}") from exc

def control_server_alive(root: Path) -> bool:
    lock=root/"SERVER.lock"
    if not lock.is_file(): return False
    try:
        doc=json.loads(lock.read_text(encoding="utf-8")); pid=int(doc.get("pid",0))
        if pid <= 0: return False
        os.kill(pid,0); return True
    except (OSError,ValueError,json.JSONDecodeError,TypeError):
        return False

def copy_control(src: Path, dst: Path, allow_live: bool) -> list[str]:
    if not src.exists(): return []
    state=src/"control.json"
    if not state.is_file(): raise BackupError(f"control state is not initialized: {src}")
    if control_server_alive(src) and not allow_live:
        raise BackupError("control plane appears active; drain/stop it before backup or use --allow-live-control")
    try:
        doc=json.loads(state.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        raise BackupError(f"invalid control.json: {exc}") from exc
    if doc.get("schema") != "ppc-lab-control-v1": raise BackupError("unsupported control-plane schema")
    copied=[]
    for p in regular_files(src, component="control"):
        rel=p.relative_to(src); q=dst/rel; q.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p,q); copied.append(rel.as_posix())
    return copied

def snapshot_state(state_root: Path, stage: Path, allow_live_control: bool) -> list[str]:
    components=[]
    evidence=state_root/"evidence"
    if evidence.exists():
        sqlite_snapshot(evidence/"evidence.sqlite3", stage/"state/evidence/evidence.sqlite3")
        # Copy exactly the immutable JSON objects referenced by the consistent DB snapshot.
        with sqlite3.connect(stage/"state/evidence/evidence.sqlite3") as conn:
            hashes=[str(r[0]) for r in conn.execute("SELECT sha256 FROM artifacts ORDER BY sha256")]
        for digest in hashes:
            src=evidence/"objects/sha256"/digest[:2]/f"{digest}.json"
            if not src.is_file(): raise BackupError(f"evidence object referenced by DB is missing: {src}")
            dst=stage/"state/evidence/objects/sha256"/digest[:2]/f"{digest}.json"; dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,dst)
        components.append("evidence")
    knowledge=state_root/"knowledge"
    if knowledge.exists():
        sqlite_snapshot(knowledge/"knowledge.sqlite3", stage/"state/knowledge/knowledge.sqlite3")
        components.append("knowledge")
    control=state_root/"control"
    if control.exists():
        copy_control(control, stage/"state/control", allow_live_control)
        components.append("control")
    if not components: raise BackupError(f"no PPC Lab persistent components found under {state_root}")
    return components

def file_inventory(stage: Path) -> list[dict[str,Any]]:
    out=[]
    for p in sorted((stage/"state").rglob("*")):
        if not p.is_file(): continue
        rel=p.relative_to(stage).as_posix()
        out.append({"path":rel,"size":p.stat().st_size,"mode":f"{stat.S_IMODE(p.stat().st_mode):04o}","sha256":sha256_file(p)})
    return out

def write_archive(stage: Path, out: Path, manifest: dict[str,Any]) -> None:
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name(out.name+f".tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
            for item in manifest["files"]:
                p=stage/item["path"]
                info=zipfile.ZipInfo(item["path"]); info.create_system=3; info.external_attr=(stat.S_IFREG|int(item["mode"],8))<<16
                zf.writestr(info,p.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
            payload=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode()
            info=zipfile.ZipInfo("BACKUP-MANIFEST.json"); info.create_system=3; info.external_attr=(stat.S_IFREG|0o600)<<16
            zf.writestr(info,payload,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        os.replace(tmp,out)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass

def create_backup(root: Path, state_root: Path, out: Path, allow_live_control: bool, deployment: Path|None) -> dict[str,Any]:
    root=root.resolve(); state_root=state_root.expanduser().resolve(); out=out.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="ppclab-backup-") as td:
        stage=Path(td); components=snapshot_state(state_root,stage,allow_live_control)
        deployment_record=None
        if deployment:
            deployment=deployment.expanduser().resolve()
            doc=json.loads(deployment.read_text(encoding="utf-8"))
            if doc.get("schema") != "ppc-lab-deployment-v1": raise BackupError("deployment metadata is not ppc-lab-deployment-v1")
            # Store the public deployment plan only; the secret environment file is never read.
            q=stage/"metadata/deployment.json"; q.parent.mkdir(parents=True,exist_ok=True)
            q.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n",encoding="utf-8")
            deployment_record={"path":"metadata/deployment.json","sha256":sha256_file(q),"size":q.stat().st_size}
        files=file_inventory(stage)
        if deployment_record:
            q=stage/deployment_record["path"]
            files.append({"path":deployment_record["path"],"size":q.stat().st_size,"mode":f"{stat.S_IMODE(q.stat().st_mode):04o}","sha256":sha256_file(q)})
            files.sort(key=lambda x:x["path"])
        manifest={
            "schema":BACKUP_SCHEMA,"backup_api":API_VERSION,"ppc_lab_version":project_version(root),"created_at":utc_now(),
            "components":components,"files":files,"deployment":deployment_record,
            "policy":{"target_binaries_copied":False,"api_secrets_copied":False,"cache_copied":False,"logs_copied":False,
                      "control_live_snapshot":bool(allow_live_control and control_server_alive(state_root/"control"))},
        }
        write_archive(stage,out,manifest)
    return {"schema":REPORT_SCHEMA,"operation":"create","ok":True,"archive":str(out),"sha256":sha256_file(out),"manifest":manifest}

def read_and_verify(archive: Path, extract_to: Path|None=None) -> tuple[dict[str,Any],list[str]]:
    archive=archive.expanduser().resolve(); errors=[]
    try:
        with zipfile.ZipFile(archive,"r") as zf:
            infos=zf.infolist(); names=[i.filename for i in infos]
            if names.count("BACKUP-MANIFEST.json") != 1: raise BackupError("backup must contain exactly one BACKUP-MANIFEST.json")
            for info in infos:
                safe_member(info.filename)
                if info.is_dir(): raise BackupError(f"directory members are not permitted: {info.filename}")
                member_mode = info.external_attr >> 16
                if stat.S_IFMT(member_mode) == stat.S_IFLNK:
                    raise BackupError(f"symlink members are not permitted: {info.filename}")
            manifest=json.loads(zf.read("BACKUP-MANIFEST.json").decode("utf-8"))
            if manifest.get("schema") != BACKUP_SCHEMA: errors.append(f"schema must be {BACKUP_SCHEMA}")
            expected={x.get("path"):x for x in manifest.get("files",[]) if isinstance(x,dict)}
            actual=set(names)-{"BACKUP-MANIFEST.json"}
            if actual != set(expected):
                missing=sorted(set(expected)-actual); extra=sorted(actual-set(expected))
                if missing: errors.append("missing members: "+", ".join(missing))
                if extra: errors.append("unexpected members: "+", ".join(extra))
            for name in sorted(actual & set(expected)):
                data=zf.read(name); item=expected[name]
                if len(data) != item.get("size"): errors.append(f"size mismatch: {name}")
                if sha256_bytes(data) != item.get("sha256"): errors.append(f"hash mismatch: {name}")
                if not (name.startswith("state/evidence/") or name.startswith("state/knowledge/") or name.startswith("state/control/") or name=="metadata/deployment.json"):
                    errors.append(f"member outside permitted backup roots: {name}")
            policy=manifest.get("policy",{})
            if policy.get("target_binaries_copied") is not False or policy.get("api_secrets_copied") is not False:
                errors.append("backup policy must declare no target binaries and no API secrets")
            if not errors and extract_to is not None:
                for name in actual:
                    data=zf.read(name); q=extract_to/safe_member(name); q.parent.mkdir(parents=True,exist_ok=True); q.write_bytes(data)
                    mode=int(expected[name].get("mode","0644"),8); os.chmod(q,mode)
    except (zipfile.BadZipFile,OSError,json.JSONDecodeError,KeyError,ValueError) as exc:
        raise BackupError(f"cannot verify backup: {exc}") from exc
    if extract_to is not None and not errors:
        # Verify database integrity and control state after extraction.
        for rel in ("state/evidence/evidence.sqlite3","state/knowledge/knowledge.sqlite3"):
            db=extract_to/rel
            if db.is_file():
                try:
                    with sqlite3.connect(db) as conn:
                        row=conn.execute("PRAGMA integrity_check").fetchone()
                        if not row or row[0] != "ok": errors.append(f"SQLite integrity failed: {rel}")
                except sqlite3.Error as exc: errors.append(f"SQLite open failed {rel}: {exc}")
        control=extract_to/"state/control/control.json"
        if control.is_file():
            try:
                doc=json.loads(control.read_text(encoding="utf-8"))
                if doc.get("schema") != "ppc-lab-control-v1": errors.append("restored control.json has unsupported schema")
            except (OSError,json.JSONDecodeError): errors.append("restored control.json is invalid JSON")
    return manifest,errors

def verify_backup(archive: Path) -> dict[str,Any]:
    with tempfile.TemporaryDirectory(prefix="ppclab-backup-verify-") as td:
        manifest,errors=read_and_verify(archive,Path(td))
    return {"schema":REPORT_SCHEMA,"operation":"verify","ok":not errors,"archive":str(archive.expanduser().resolve()),
            "sha256":sha256_file(archive.expanduser().resolve()),"manifest":manifest,"errors":errors}

def restore_backup(archive: Path, state_root: Path, force: bool, deployment_out: Path|None) -> dict[str,Any]:
    state_root=state_root.expanduser().resolve(); archive=archive.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="ppclab-restore-") as td:
        stage=Path(td); manifest,errors=read_and_verify(archive,stage)
        if errors: raise BackupError("backup verification failed: "+"; ".join(errors))
        components=[c for c in manifest.get("components",[]) if c in ALLOWED_COMPONENTS]
        if not components: raise BackupError("backup contains no restorable components")
        existing=[c for c in components if (state_root/c).exists()]
        if existing and not force: raise BackupError("destination already contains state: "+", ".join(existing)+"; use --force")
        state_root.mkdir(parents=True,exist_ok=True)
        safety=None
        if existing:
            stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safety=state_root/f".pre-restore-{stamp}-{os.getpid()}"; safety.mkdir()
            for c in existing: shutil.move(str(state_root/c),str(safety/c))
        installed=[]
        try:
            for c in components:
                src=stage/"state"/c
                if src.exists(): shutil.move(str(src),str(state_root/c)); installed.append(c)
            if deployment_out and (stage/"metadata/deployment.json").is_file():
                deployment_out=deployment_out.expanduser().resolve(); deployment_out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(stage/"metadata/deployment.json",deployment_out); os.chmod(deployment_out,0o600)
        except Exception:
            for c in installed:
                q=state_root/c
                if q.exists(): shutil.rmtree(q)
            if safety:
                for c in existing:
                    q=safety/c
                    if q.exists(): shutil.move(str(q),str(state_root/c))
            raise
    return {"schema":REPORT_SCHEMA,"operation":"restore","ok":True,"archive":str(archive),"state_root":str(state_root),
            "components":installed,"pre_restore":str(safety) if safety else None,"target_binaries_copied":False}

def emit(doc:dict[str,Any],as_json:bool)->None:
    if as_json: print(json.dumps(doc,indent=2,sort_keys=True))
    else:
        print(f"{doc.get('operation')}={'PASS' if doc.get('ok') else 'FAIL'}")
        if doc.get("archive"): print(f"archive={doc['archive']}")
        for e in doc.get("errors",[]): print("ERROR: "+e,file=sys.stderr)

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("create"); p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]); p.add_argument("--state-root",type=Path,default=Path("/var/lib/ppc-lab")); p.add_argument("--out",type=Path,required=True); p.add_argument("--deployment",type=Path); p.add_argument("--allow-live-control",action="store_true"); p.add_argument("--json",action="store_true")
    p=sub.add_parser("verify"); p.add_argument("archive",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("inspect"); p.add_argument("archive",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("restore"); p.add_argument("archive",type=Path); p.add_argument("--state-root",type=Path,default=Path("/var/lib/ppc-lab")); p.add_argument("--force",action="store_true"); p.add_argument("--deployment-out",type=Path); p.add_argument("--json",action="store_true")
    ns=ap.parse_args()
    try:
        if ns.cmd=="create": doc=create_backup(ns.root,ns.state_root,ns.out,ns.allow_live_control,ns.deployment)
        elif ns.cmd=="verify": doc=verify_backup(ns.archive)
        elif ns.cmd=="inspect":
            manifest,errors=read_and_verify(ns.archive,None); doc={"schema":REPORT_SCHEMA,"operation":"inspect","ok":not errors,"archive":str(ns.archive.expanduser().resolve()),"manifest":manifest,"errors":errors}
        else: doc=restore_backup(ns.archive,ns.state_root,ns.force,ns.deployment_out)
        emit(doc,ns.json); return 0 if doc.get("ok") else 1
    except (BackupError,OSError,ValueError,json.JSONDecodeError,sqlite3.Error) as exc:
        print(f"ppc-lab-backup: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
