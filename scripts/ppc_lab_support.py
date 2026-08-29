#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab LTS diagnostics and redacted support-bundle tooling."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "ppc-lab-support-report-v1"
MANIFEST_SCHEMA = "ppc-lab-support-bundle-v1"
SUPPORT_API = 1
MAX_LOG_BYTES = 2 * 1024 * 1024

class SupportError(RuntimeError):
    pass

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")

def scripts_dir() -> Path:
    return Path(__file__).resolve().parent

def add_scripts_path() -> None:
    p = str(scripts_dir())
    if p not in sys.path:
        sys.path.insert(0, p)

def safe_system() -> dict[str, Any]:
    return {
        "os": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
    }

def sanitize_text(text: str, replacements: dict[str, str] | None = None) -> tuple[str, int]:
    count = 0
    repl = replacements or {}
    for raw, token in sorted(repl.items(), key=lambda x: len(x[0]), reverse=True):
        if raw:
            n = text.count(raw)
            if n:
                text = text.replace(raw, token); count += n
    patterns = [
        (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"), r"\1<redacted>"),
        (re.compile(r"(?i)((?:access[_-]?token|api[_-]?key|password|secret|token)\s*[=:]\s*)[^\s,;]+"), r"\1<redacted>"),
        (re.compile(r"(?i)(\"(?:access[_-]?token|api[_-]?key|password|secret|token)\"\s*:\s*\")[^\"]+(\")"), r"\1<redacted>\2"),
    ]
    for pat, replacement in patterns:
        text, n = pat.subn(replacement, text); count += n
    return text, count

def sanitize_obj(value: Any, replacements: dict[str, str] | None = None) -> Any:
    secret_keys = {"authorization", "password", "secret", "token", "access_token", "api_key", "apikey"}
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in secret_keys:
                out[k] = "<redacted>"
            else:
                out[k] = sanitize_obj(v, replacements)
        return out
    if isinstance(value, list):
        return [sanitize_obj(v, replacements) for v in value]
    if isinstance(value, str):
        return sanitize_text(value, replacements)[0]
    return value

def replacements_for(evidence: Path | None, knowledge: Path | None, control: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    home = str(Path.home())
    if home and home != "/": out[home] = "$HOME"
    for path, name in [(evidence, "$EVIDENCE"), (knowledge, "$KNOWLEDGE"), (control, "$CONTROL")]:
        if path:
            try: out[str(path.expanduser().resolve())] = name
            except OSError: pass
    return out

def compact_control(control: Path) -> dict[str, Any]:
    add_scripts_path()
    from ppc_lab_control import ensure_root, make_telemetry, read_history
    root = ensure_root(control)
    telemetry = make_telemetry(root)
    failures=[]
    for rec in reversed(read_history(root)):
        if rec.get("status") not in {"complete", "success"}:
            failures.append({k: rec.get(k) for k in ("id","status","returncode","priority","attempts","submitted_unix","started_unix","finished_unix")})
        if len(failures) >= 20: break
    return {"telemetry": telemetry, "recent_failures": failures}

def diagnose(core: str | None, tool_dir: Path | None, evidence: Path | None, knowledge: Path | None, control: Path | None) -> dict[str, Any]:
    add_scripts_path()
    from ppc_lab_platform import PLATFORM_VERSION, resolve_core, status, run, upgrade_report
    from ppc_lab_compat import build_snapshot
    replacements = replacements_for(evidence, knowledge, control)
    doc: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "support_api": SUPPORT_API,
        "platform_version": PLATFORM_VERSION,
        "generated_at": utc_now(),
        "system": safe_system(),
        "checks": {},
        "warnings": [],
    }
    root = scripts_dir().parent
    try:
        core_path = resolve_core(core, tool_dir)
        pstatus = status(core_path, tool_dir)
        doctor = run([str(core_path), "doctor"], timeout=60)
        caps = run([str(core_path), "capabilities", "--json"], timeout=30)
        doc["checks"]["platform"] = {"ok": bool(pstatus.get("ready")), "status": pstatus}
        doc["checks"]["core_doctor"] = {"ok": doctor.returncode == 0 and "status=PASS" in doctor.stdout, "returncode": doctor.returncode, "stdout": doctor.stdout[-8192:], "stderr": doctor.stderr[-8192:]}
        if caps.returncode == 0:
            try: cdoc=json.loads(caps.stdout)
            except json.JSONDecodeError: cdoc={"parse_error": True, "raw": caps.stdout[-4096:]}
            doc["checks"]["capabilities"] = {"ok": True, "document": cdoc}
        else:
            doc["checks"]["capabilities"] = {"ok": False, "returncode": caps.returncode, "stderr": caps.stderr[-4096:]}
    except Exception as exc:
        doc["checks"]["platform"] = {"ok": False, "error": str(exc)}
    if (root / "CMakeLists.txt").is_file():
        try:
            snap=build_snapshot(root)
            doc["checks"]["compatibility"]={"ok": True, "snapshot": snap}
        except Exception as exc:
            doc["checks"]["compatibility"]={"ok": False, "error": str(exc)}
    else:
        doc["checks"]["compatibility"]={"ok": True, "installed_layout": True, "note": "source-tree compatibility snapshot unavailable; core/platform version contracts were checked instead"}
    try:
        persisted=upgrade_report(evidence, knowledge, control)
        doc["checks"]["persisted_state"]={"ok": bool(persisted.get("compatible")), "report": persisted}
    except Exception as exc:
        doc["checks"]["persisted_state"]={"ok": False, "error": str(exc)}
    if evidence:
        try:
            from ppc_lab_evidence import report, verify
            doc["checks"]["evidence"]={"ok": bool((v:=verify(evidence)).get("ok")), "report": report(evidence), "verify": v}
        except Exception as exc: doc["checks"]["evidence"]={"ok": False, "error": str(exc)}
    if knowledge:
        try:
            from ppc_lab_knowledge import report_graph, verify_graph
            doc["checks"]["knowledge"]={"ok": bool((v:=verify_graph(knowledge)).get("ok")), "report": report_graph(knowledge), "verify": v}
        except Exception as exc: doc["checks"]["knowledge"]={"ok": False, "error": str(exc)}
    if control:
        try:
            doc["checks"]["control"]={"ok": True, **compact_control(control)}
        except Exception as exc: doc["checks"]["control"]={"ok": False, "error": str(exc)}
    doc = sanitize_obj(doc, replacements)
    failed=[name for name, check in doc["checks"].items() if isinstance(check,dict) and check.get("ok") is False]
    doc["healthy"] = not failed
    doc["failed_checks"] = failed
    if not evidence and not knowledge and not control:
        doc["warnings"].append("No persisted-state roots were supplied; evidence/knowledge/control integrity was not audited.")
    return doc

def read_text_log(path: Path, replacements: dict[str,str]) -> tuple[bytes,int]:
    p=path.expanduser().resolve(strict=True)
    size=p.stat().st_size
    if size > MAX_LOG_BYTES: raise SupportError(f"log exceeds {MAX_LOG_BYTES} bytes: {p}")
    raw=p.read_bytes()
    if b"\x00" in raw: raise SupportError(f"refusing non-text log: {p}")
    try: text=raw.decode("utf-8")
    except UnicodeDecodeError as exc: raise SupportError(f"log is not UTF-8 text: {p}") from exc
    clean,n=sanitize_text(text,replacements)
    return clean.encode("utf-8"),n

def make_bundle(out: Path, report: dict[str,Any], logs: list[Path], replacements: dict[str,str]) -> dict[str,Any]:
    out=out.expanduser().resolve(); out.parent.mkdir(parents=True,exist_ok=True)
    members: dict[str,bytes] = {"support-report.json": json_bytes(report)}
    redactions=0
    used=set()
    for i,path in enumerate(logs):
        data,n=read_text_log(path,replacements); redactions += n
        base=re.sub(r"[^A-Za-z0-9._-]+","_",path.name) or f"log-{i}.txt"
        name=f"logs/{i:02d}-{base}.txt"
        if name in used: raise SupportError(f"duplicate log member: {name}")
        used.add(name); members[name]=data
    manifest={
        "schema": MANIFEST_SCHEMA, "support_api": SUPPORT_API,
        "platform_version": report.get("platform_version"), "created_at": report.get("generated_at"),
        "target_binaries_included": False, "redactions_applied": redactions,
        "allowed_members": ["support-report.json","SUPPORT-MANIFEST.json","logs/*.txt"],
        "files": [{"path":name,"size":len(data),"sha256":sha256_bytes(data)} for name,data in sorted(members.items())],
    }
    members["SUPPORT-MANIFEST.json"] = json_bytes(manifest)
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for name,data in sorted(members.items()):
            zi=zipfile.ZipInfo(name,(2000,1,1,0,0,0)); zi.create_system=3; zi.external_attr=(0o100644<<16)
            zf.writestr(zi,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    return manifest

def verify_bundle(path: Path) -> dict[str,Any]:
    p=path.expanduser().resolve(strict=True); errors=[]
    with zipfile.ZipFile(p,"r") as zf:
        names=zf.namelist()
        if len(names)!=len(set(names)): errors.append("duplicate archive members")
        allowed=lambda n: n in {"support-report.json","SUPPORT-MANIFEST.json"} or (n.startswith("logs/") and n.endswith(".txt") and ".." not in Path(n).parts)
        unexpected=[n for n in names if not allowed(n)]
        if unexpected: errors.append("unexpected archive members: "+", ".join(sorted(unexpected)))
        if "SUPPORT-MANIFEST.json" not in names: return {"schema":"ppc-lab-support-bundle-verify-v1","ok":False,"errors":errors+["missing SUPPORT-MANIFEST.json"]}
        try: manifest=json.loads(zf.read("SUPPORT-MANIFEST.json"))
        except Exception as exc: return {"schema":"ppc-lab-support-bundle-verify-v1","ok":False,"errors":errors+[f"invalid manifest: {exc}"]}
        if manifest.get("schema")!=MANIFEST_SCHEMA: errors.append(f"manifest schema must be {MANIFEST_SCHEMA}")
        if manifest.get("target_binaries_included") is not False: errors.append("manifest must declare target_binaries_included=false")
        listed={x.get("path"):x for x in manifest.get("files",[]) if isinstance(x,dict)}
        for name in names:
            if name=="SUPPORT-MANIFEST.json": continue
            item=listed.get(name)
            if item is None: errors.append(f"unlisted member: {name}"); continue
            data=zf.read(name)
            if item.get("sha256")!=sha256_bytes(data): errors.append(f"hash mismatch: {name}")
            if item.get("size")!=len(data): errors.append(f"size mismatch: {name}")
        for name in sorted(set(listed)-set(names)): errors.append(f"manifest references missing member: {name}")
        if "support-report.json" in names:
            try:
                report=json.loads(zf.read("support-report.json"))
                if report.get("schema")!=REPORT_SCHEMA: errors.append(f"report schema must be {REPORT_SCHEMA}")
            except Exception as exc: errors.append(f"invalid support report: {exc}")
    return {"schema":"ppc-lab-support-bundle-verify-v1","ok":not errors,"bundle":str(p),"errors":errors}

def main() -> int:
    ap=argparse.ArgumentParser(prog="ppc-lab-support",description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    def common(p:argparse.ArgumentParser)->None:
        p.add_argument("--core"); p.add_argument("--tool-dir",type=Path); p.add_argument("--evidence",type=Path); p.add_argument("--knowledge",type=Path); p.add_argument("--control",type=Path)
    p=sub.add_parser("diagnose"); common(p); p.add_argument("--json",action="store_true")
    p=sub.add_parser("bundle"); common(p); p.add_argument("--out",type=Path,required=True); p.add_argument("--log",type=Path,action="append",default=[]); p.add_argument("--json",action="store_true")
    p=sub.add_parser("verify"); p.add_argument("bundle",type=Path); p.add_argument("--json",action="store_true")
    ns=ap.parse_args()
    try:
        if ns.cmd=="verify":
            doc=verify_bundle(ns.bundle)
        else:
            report=diagnose(ns.core,ns.tool_dir,ns.evidence,ns.knowledge,ns.control)
            if ns.cmd=="diagnose": doc=report
            else:
                repl=replacements_for(ns.evidence,ns.knowledge,ns.control)
                manifest=make_bundle(ns.out,report,ns.log,repl)
                check=verify_bundle(ns.out)
                doc={"schema":"ppc-lab-support-bundle-result-v1","ok":check["ok"],"bundle":str(ns.out.expanduser().resolve()),"manifest":manifest,"verify":check}
        if ns.json: print(json.dumps(doc,indent=2,sort_keys=True))
        else:
            if ns.cmd=="diagnose": print(f"support health={'PASS' if doc['healthy'] else 'FAIL'} failed={','.join(doc['failed_checks']) or '-'}")
            elif ns.cmd=="bundle": print(f"bundle={doc['bundle']} verify={'PASS' if doc['ok'] else 'FAIL'}")
            else: print(f"support bundle verify={'PASS' if doc['ok'] else 'FAIL'}")
        if ns.cmd=="diagnose": return 0 if doc["healthy"] else 1
        return 0 if doc["ok"] else 1
    except (SupportError,OSError,json.JSONDecodeError,zipfile.BadZipFile,ValueError) as exc:
        print(f"ppc-lab-support: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
