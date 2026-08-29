#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab v3 mature-platform operator and upgrade surface.

This command does not add another execution engine.  It consolidates health,
upgrade compatibility, persisted-state migration, and a synthetic end-to-end
acceptance scenario across the stable PPC Lab subsystem contracts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PLATFORM_VERSION = "3.9.2"
STATUS_SCHEMA = "ppc-lab-platform-status-v1"
UPGRADE_SCHEMA = "ppc-lab-upgrade-report-v1"
ACCEPTANCE_SCHEMA = "ppc-lab-acceptance-report-v1"
CONTROL_SCHEMA = "ppc-lab-control-v1"
CONTROL_ITEM_SCHEMA = "ppc-lab-control-item-v1"
SUPPORTED_PERSISTED_SCHEMA_VERSION = 1


class PlatformError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PlatformError(f"command timed out after {timeout:g}s: {' '.join(cmd)}") from exc


def tool_cmd(path: Path, *args: str) -> list[str]:
    return [sys.executable, str(path), *args] if path.suffix == ".py" else [str(path), *args]


def resolve_core(value: str | None, tool_dir: Path | None) -> Path:
    candidates: list[Path] = []
    if value: candidates.append(Path(value).expanduser())
    if tool_dir:
        candidates += [tool_dir / "ppc-lab", tool_dir / "ppc_lab"]
    sibling = Path(__file__).resolve().parent
    candidates += [sibling / "ppc-lab", sibling.parent / "build" / "release" / "ppc-lab"]
    found = shutil.which("ppc-lab")
    if found: candidates.append(Path(found))
    for p in candidates:
        try: q = p.resolve()
        except OSError: continue
        if q.is_file() and os.access(q, os.X_OK): return q
    raise PlatformError("cannot find ppc-lab core executable; use --core")


TOOL_SOURCES = {
    "worker": "ppc_lab_worker.py", "orchestrate": "ppc_lab_orchestrate.py", "fleet": "ppc_lab_fleet.py",
    "evidence": "ppc_lab_evidence.py", "api": "ppc_lab_api.py", "corpus": "ppc_lab_corpus.py",
    "triage": "ppc_lab_triage.py", "explore": "ppc_lab_explore.py", "prioritize": "ppc_lab_prioritize.py",
    "campaign": "ppc_lab_campaign.py", "schedule": "ppc_lab_schedule.py", "control": "ppc_lab_control.py",
    "knowledge": "ppc_lab_knowledge.py", "hypothesize": "ppc_lab_hypothesize.py",
    "trace-analyze": "ppc_trace_analyze.py", "trace-diff": "ppc_trace_diff.py",
    "support": "ppc_lab_support.py", "backup": "ppc_lab_backup.py", "observe": "ppc_lab_observe.py",
}


def installed_name(key: str) -> str:
    return "ppc-lab-" + key


def resolve_companion(key: str, tool_dir: Path | None) -> Path | None:
    source = TOOL_SOURCES[key]
    candidates: list[Path] = []
    if tool_dir:
        candidates += [tool_dir / installed_name(key), tool_dir / source]
    sibling = Path(__file__).resolve().parent
    candidates += [sibling / installed_name(key), sibling / source]
    found = shutil.which(installed_name(key))
    if found: candidates.append(Path(found))
    for p in candidates:
        try: q = p.resolve()
        except OSError: continue
        if q.is_file(): return q
    return None


def resolve_tools(tool_dir: Path | None, required: set[str] | None = None) -> dict[str, Path]:
    tools: dict[str, Path] = {}
    missing=[]
    for key in TOOL_SOURCES:
        p=resolve_companion(key, tool_dir)
        if p: tools[key]=p
        elif required is None or key in required: missing.append(key)
    if missing: raise PlatformError("missing PPC Lab companion tools: " + ", ".join(missing))
    return tools


def core_capabilities(core: Path) -> dict[str, Any]:
    p=run([str(core), "capabilities", "--json"], timeout=30)
    if p.returncode != 0: raise PlatformError(f"core capabilities failed: {p.stderr.strip() or p.stdout.strip()}")
    doc=json.loads(p.stdout)
    if doc.get("schema") != "ppc-lab-capabilities-v1": raise PlatformError("unexpected core capability schema")
    return doc


def status(core: Path, tool_dir: Path | None) -> dict[str, Any]:
    caps=core_capabilities(core)
    tools=resolve_tools(tool_dir, required=set())
    expected=set(TOOL_SOURCES)
    return {
        "schema": STATUS_SCHEMA, "platform_version": PLATFORM_VERSION, "checked_at": utc_now(),
        "core": {"path": str(core), "version": caps.get("version"), "host": caps.get("host"), "backends": caps.get("backends")},
        "companions": {k: {"available": k in tools, "path": str(tools[k]) if k in tools else None} for k in sorted(expected)},
        "ready": all(k in tools for k in expected),
    }


def sqlite_meta(db: Path, expected_tables: set[str]) -> dict[str, Any]:
    if not db.is_file(): return {"present": False, "compatible": False, "reason": f"missing {db.name}"}
    try:
        with sqlite3.connect(db) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not expected_tables.issubset(tables):
                return {"present": True, "compatible": False, "reason": "required tables missing", "tables": sorted(tables)}
            meta=dict(conn.execute("SELECT key,value FROM meta")) if "meta" in tables else {}
            sv=int(meta.get("schema_version", "0"))
            return {"present": True, "compatible": sv == SUPPORTED_PERSISTED_SCHEMA_VERSION,
                    "schema_version": sv, "platform_format_version": int(meta.get("platform_format_version", "0")),
                    "last_migrated_by": meta.get("last_migrated_by"), "tables": sorted(tables)}
    except (sqlite3.Error, ValueError) as exc:
        return {"present": True, "compatible": False, "reason": str(exc)}


def check_control(root: Path) -> dict[str, Any]:
    state=root / "control.json"
    if not state.is_file(): return {"present": False, "compatible": False, "reason": "missing control.json"}
    try:
        doc=read_json(state)
        compatible=doc.get("schema") == CONTROL_SCHEMA
        bad=[]
        q=root / "queue"
        if q.is_dir():
            for p in sorted(q.glob("*.json")):
                item=read_json(p)
                if not isinstance(item,dict) or item.get("schema") != CONTROL_ITEM_SCHEMA: bad.append(p.name)
        return {"present": True, "compatible": compatible and not bad, "schema": doc.get("schema"),
                "format_version": int(doc.get("format_version",0) or 0), "last_migrated_by": doc.get("last_migrated_by"),
                "invalid_queue_items": bad}
    except (OSError,json.JSONDecodeError,ValueError) as exc:
        return {"present": True, "compatible": False, "reason": str(exc)}


def upgrade_report(evidence: Path | None, knowledge: Path | None, control: Path | None) -> dict[str, Any]:
    parts: dict[str,Any]={}
    if evidence:
        parts["evidence"] = sqlite_meta(evidence.expanduser().resolve()/"evidence.sqlite3", {"meta","artifacts","sources","inputs"})
    if knowledge:
        parts["knowledge"] = sqlite_meta(knowledge.expanduser().resolve()/"knowledge.sqlite3", {"meta","documents","nodes","edges"})
    if control:
        parts["control"] = check_control(control.expanduser().resolve())
    for name,item in parts.items():
        if item.get("compatible"):
            current=int(item.get("platform_format_version", item.get("format_version",0)) or 0)
            item["migration_required"] = current < 1
        else: item["migration_required"] = False
    return {"schema":UPGRADE_SCHEMA,"platform_version":PLATFORM_VERSION,"checked_at":utc_now(),"components":parts,
            "compatible": all(v.get("compatible") for v in parts.values()) if parts else True,
            "migration_required": any(v.get("migration_required") for v in parts.values())}


def backup_sqlite(db: Path) -> Path:
    backup=db.with_name(db.name + ".pre-v3.0.0.bak")
    if backup.exists(): return backup
    with sqlite3.connect(db) as src, sqlite3.connect(backup) as dst: src.backup(dst)
    return backup


def migrate_sqlite(root: Path, db_name: str, expected_tables: set[str]) -> dict[str,Any]:
    db=root/db_name; info=sqlite_meta(db,expected_tables)
    if not info.get("compatible"): raise PlatformError(f"cannot migrate incompatible {db}: {info.get('reason','schema mismatch')}")
    backup=backup_sqlite(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('platform_format_version','1')")
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_migrated_by',?)",(PLATFORM_VERSION,)); conn.commit()
    return {"path":str(root),"backup":str(backup),"changed":int(info.get("platform_format_version",0) or 0)<1}


def migrate_control(root: Path) -> dict[str,Any]:
    info=check_control(root)
    if not info.get("compatible"): raise PlatformError(f"cannot migrate incompatible control plane: {info.get('reason','schema mismatch')}")
    state=root/"control.json"; backup=root/"control.json.pre-v3.0.0.bak"
    if not backup.exists(): shutil.copy2(state,backup)
    doc=read_json(state); changed=int(doc.get("format_version",0) or 0)<1
    doc["format_version"]=1; doc["last_migrated_by"]=PLATFORM_VERSION; atomic_json(state,doc)
    return {"path":str(root),"backup":str(backup),"changed":changed}


def migrate(evidence: Path | None, knowledge: Path | None, control: Path | None) -> dict[str,Any]:
    result={"schema":UPGRADE_SCHEMA,"platform_version":PLATFORM_VERSION,"migrated_at":utc_now(),"components":{}}
    if evidence: result["components"]["evidence"]=migrate_sqlite(evidence.expanduser().resolve(),"evidence.sqlite3",{"meta","artifacts","sources","inputs"})
    if knowledge: result["components"]["knowledge"]=migrate_sqlite(knowledge.expanduser().resolve(),"knowledge.sqlite3",{"meta","documents","nodes","edges"})
    if control: result["components"]["control"]=migrate_control(control.expanduser().resolve())
    result["postcheck"]=upgrade_report(evidence,knowledge,control)
    return result


def make_loop_elf(path: Path) -> None:
    code_addr=0x00100000; code_off=0x100
    blob=bytearray(0x114); blob[:7]=b"\x7fELF\x01\x02\x01"
    def w16(off:int,v:int)->None: blob[off:off+2]=struct.pack(">H",v)
    def w32(off:int,v:int)->None: blob[off:off+4]=struct.pack(">I",v)
    w16(16,2); w16(18,20); w32(20,1); w32(24,code_addr); w32(28,52); w16(40,52); w16(42,32); w16(44,1)
    ph=52
    for off,val in [(0,1),(4,code_off),(8,code_addr),(12,code_addr),(16,20),(20,20),(24,5),(28,4)]: w32(ph+off,val)
    # cmpwi r3,0 ; beq done ; addi r3,r3,-1 ; b loop ; blr
    for i,ins in enumerate([0x2C030000,0x4182000C,0x3863FFFF,0x4BFFFFF4,0x4E800020]): w32(code_off+i*4,ins)
    path.write_bytes(blob)


def must(cmd: list[str], stage: str, cwd: Path | None = None, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    p=run(cmd,cwd=cwd,timeout=timeout)
    if p.returncode != 0: raise PlatformError(f"{stage} failed ({p.returncode}): {p.stderr.strip() or p.stdout.strip()}")
    return p


def acceptance(core: Path, tool_dir: Path | None, workspace: Path) -> dict[str,Any]:
    required={"worker","explore","evidence","knowledge","hypothesize"}
    tools=resolve_tools(tool_dir,required=required)
    workspace=workspace.expanduser().resolve(); workspace.mkdir(parents=True,exist_ok=True)
    target=workspace/"loop.elf"; make_loop_elf(target)
    stages=[]
    analysis=json.loads(must([str(core),"analyze",str(target),"--json"],"binary intake").stdout)
    stages.append({"stage":"intake","ok":analysis.get("format")=="ELF32-PPC-BE","format":analysis.get("format")})
    manifest={"schema":"ppc-lab-exploration-v1","strategy":"cartesian","max_cases":3,
        "base_job":{"schema":"ppc-lab-job-v1","id":"v3-acceptance","image":{"path":"loop.elf"},
                    "execution":{"backend":"builtin","max_instructions":5000},"registers":{"r3":0}},
        "axes":[{"path":"registers.r3","values":[0,256,512]}]}
    mp=workspace/"exploration.json"; atomic_json(mp,manifest); exp=workspace/"exploration"
    must(tool_cmd(tools["explore"],str(mp),"--out",str(exp),"--ppc-lab",str(core),"--worker",str(tools["worker"]),"--root",str(workspace)),"guided exploration",timeout=180)
    summary=read_json(exp/"summary.json"); stages.append({"stage":"exploration","ok":summary.get("successful_cases")==3,"cases":summary.get("evaluated_cases")})
    evidence=workspace/"evidence"; must(tool_cmd(tools["evidence"],"init",str(evidence)),"evidence init")
    must(tool_cmd(tools["evidence"],"ingest",str(evidence),str(exp),"--strict","--json"),"evidence ingest")
    ev=json.loads(must(tool_cmd(tools["evidence"],"verify",str(evidence),"--json"),"evidence verify").stdout)
    stages.append({"stage":"evidence","ok":bool(ev.get("ok")),"artifacts":ev.get("artifacts")})
    report=workspace/"hypotheses.json"
    must(tool_cmd(tools["hypothesize"],"analyze",str(exp),"--manifest",str(mp),"--json",str(report)),"hypothesis analysis")
    hdoc=read_json(report); hs=hdoc.get("hypotheses") or []
    if not hs: raise PlatformError("hypothesis analysis produced no candidates")
    promoted=workspace/"promoted.json"
    must(tool_cmd(tools["hypothesize"],"promote",str(report),str(hs[0]["id"]),"--evidence",str(exp),"--json",str(promoted)),"hypothesis promotion")
    pdoc=read_json(promoted); stages.append({"stage":"hypothesis","ok":pdoc.get("status")=="supported","role":pdoc.get("role"),"confidence":pdoc.get("confidence")})
    graph=workspace/"knowledge"; must(tool_cmd(tools["knowledge"],"init",str(graph),"--json"),"knowledge init")
    must(tool_cmd(tools["knowledge"],"ingest",str(graph),str(report),str(promoted),"--json"),"knowledge ingest")
    kg=json.loads(must(tool_cmd(tools["knowledge"],"verify",str(graph),"--json"),"knowledge verify").stdout)
    q=json.loads(must(tool_cmd(tools["knowledge"],"query",str(graph),"--type","hypothesis","--json"),"knowledge query").stdout)
    stages.append({"stage":"knowledge","ok":bool(kg.get("ok",True)) and int(q.get("count",0))>=1,"hypotheses":q.get("count")})
    ok=all(bool(s["ok"]) for s in stages)
    return {"schema":ACCEPTANCE_SCHEMA,"platform_version":PLATFORM_VERSION,"ran_at":utc_now(),"ok":ok,
            "target":{"path":str(target),"sha256":sha256_file(target)},"stages":stages,
            "workspace":str(workspace),"note":"Synthetic redistributable fixture only; no private target binaries are archived."}


def output(doc: dict[str,Any], as_json: bool) -> None:
    if as_json: print(json.dumps(doc,indent=2,sort_keys=True)); return
    print(f"schema={doc.get('schema')} platform={doc.get('platform_version')}")
    if doc.get("schema")==STATUS_SCHEMA:
        print(f"core={doc['core']['version']} ready={'yes' if doc['ready'] else 'no'}")
        for k,v in doc["companions"].items(): print(f"{k}={'ok' if v['available'] else 'missing'}")
    elif doc.get("schema")==UPGRADE_SCHEMA:
        print(f"compatible={'yes' if doc.get('compatible',doc.get('postcheck',{}).get('compatible')) else 'no'} migration_required={'yes' if doc.get('migration_required',False) else 'no'}")
        for k,v in doc.get("components",{}).items(): print(f"{k} compatible={v.get('compatible','migrated')} format={v.get('platform_format_version',v.get('format_version','-'))}")
    elif doc.get("schema")==ACCEPTANCE_SCHEMA:
        for s in doc["stages"]: print(f"{s['stage']}={'PASS' if s['ok'] else 'FAIL'}")
        print(f"status={'PASS' if doc['ok'] else 'FAIL'}")


def add_persisted_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--evidence",type=Path); p.add_argument("--knowledge",type=Path); p.add_argument("--control",type=Path)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("status",help="inspect core + companion-tool readiness"); p.add_argument("--core"); p.add_argument("--tool-dir",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("doctor",help="run whole-platform health and optional persisted-state checks"); p.add_argument("--core"); p.add_argument("--tool-dir",type=Path); add_persisted_args(p); p.add_argument("--json",action="store_true")
    p=sub.add_parser("upgrade-check",help="audit persisted evidence/knowledge/control compatibility"); add_persisted_args(p); p.add_argument("--json",action="store_true")
    p=sub.add_parser("migrate",help="apply idempotent v3 persisted-state metadata migrations with backups"); add_persisted_args(p); p.add_argument("--yes",action="store_true",required=True); p.add_argument("--json",action="store_true")
    p=sub.add_parser("acceptance",help="run synthetic end-to-end mature-platform acceptance"); p.add_argument("--core"); p.add_argument("--tool-dir",type=Path); p.add_argument("--workspace",type=Path,required=True); p.add_argument("--json",action="store_true")
    ns=ap.parse_args()
    try:
        if ns.cmd=="status": doc=status(resolve_core(ns.core,ns.tool_dir),ns.tool_dir)
        elif ns.cmd=="doctor":
            core=resolve_core(ns.core,ns.tool_dir); doc=status(core,ns.tool_dir); d=must([str(core),"doctor"],"core doctor",timeout=60)
            doc["core_doctor"]={"ok":"status=PASS" in d.stdout}; doc["persisted"]=upgrade_report(ns.evidence,ns.knowledge,ns.control); doc["ready"]=doc["ready"] and doc["core_doctor"]["ok"] and doc["persisted"]["compatible"]
        elif ns.cmd=="upgrade-check": doc=upgrade_report(ns.evidence,ns.knowledge,ns.control)
        elif ns.cmd=="migrate": doc=migrate(ns.evidence,ns.knowledge,ns.control)
        else: doc=acceptance(resolve_core(ns.core,ns.tool_dir),ns.tool_dir,ns.workspace)
        output(doc,ns.json)
        if ns.cmd in {"status","doctor"}: return 0 if doc.get("ready") else 1
        if ns.cmd=="upgrade-check": return 0 if doc.get("compatible") else 2
        if ns.cmd=="acceptance": return 0 if doc.get("ok") else 1
        return 0
    except (PlatformError,OSError,json.JSONDecodeError,sqlite3.Error,ValueError) as exc:
        print(f"ppc-lab-platform: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
