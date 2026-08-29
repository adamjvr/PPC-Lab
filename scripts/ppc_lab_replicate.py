#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Offline-safe PPC Lab evidence/knowledge replication and multi-site receipts."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

REPLICATION_API_VERSION = 1
STORE_SCHEMA = "ppc-lab-replication-store-v1"
BUNDLE_SCHEMA = "ppc-lab-replication-bundle-v1"
RECEIPT_SCHEMA = "ppc-lab-replication-receipt-v1"
STATUS_SCHEMA = "ppc-lab-replication-status-v1"
VERIFY_SCHEMA = "ppc-lab-replication-verify-v1"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
SITE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

class ReplicationError(RuntimeError):
    pass

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass

def read_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplicationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ReplicationError(f"expected JSON object: {path}")
    return doc

def validate_site(site: str) -> str:
    if not SITE_RE.fullmatch(site):
        raise ReplicationError("site id must be 1..64 characters using A-Z a-z 0-9 . _ -")
    return site

def ensure_store(root: Path, *, create: bool = False, site: str | None = None) -> tuple[Path, dict[str, Any]]:
    root = root.expanduser().resolve()
    state_path = root / "replication.json"
    if create:
        if site is None:
            raise ReplicationError("--site is required when initializing a replication store")
        validate_site(site)
        root.mkdir(parents=True, exist_ok=True)
        (root / "receipts").mkdir(exist_ok=True)
        (root / "control-history").mkdir(exist_ok=True)
        if not state_path.exists():
            write_json(state_path, {
                "schema": STORE_SCHEMA,
                "replication_api": REPLICATION_API_VERSION,
                "site": site,
                "next_generation": 1,
                "created_at": now_iso(),
            })
    if not state_path.is_file():
        raise ReplicationError(f"replication store is not initialized: {root}; run init first")
    state = read_json(state_path)
    if state.get("schema") != STORE_SCHEMA or int(state.get("replication_api", -1)) != REPLICATION_API_VERSION:
        raise ReplicationError(f"unsupported replication store format: {state_path}")
    validate_site(str(state.get("site", "")))
    if site is not None and state.get("site") != site:
        raise ReplicationError(f"replication store site mismatch: expected {site}, found {state.get('site')}")
    return root, state

def load_module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReplicationError(f"cannot load helper module {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def collect_evidence(store: Path) -> list[tuple[str, bytes]]:
    store = store.expanduser().resolve()
    db = store / "evidence.sqlite3"
    if not db.is_file():
        raise ReplicationError(f"evidence store is not initialized: {store}")
    out: list[tuple[str, bytes]] = []
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT sha256 FROM artifacts ORDER BY sha256").fetchall()
    for (digest,) in rows:
        digest = str(digest).lower()
        if not HEX64_RE.fullmatch(digest):
            raise ReplicationError(f"invalid evidence artifact digest in database: {digest}")
        path = store / "objects" / "sha256" / digest[:2] / f"{digest}.json"
        if not path.is_file():
            raise ReplicationError(f"evidence object missing: {path}")
        raw = path.read_bytes()
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReplicationError(f"invalid evidence object JSON: {path}: {exc}") from exc
        canonical = canonical_json(doc)
        if sha256_bytes(canonical) != digest:
            raise ReplicationError(f"evidence object semantic hash mismatch: {path}")
        out.append((f"evidence/{digest}.json", canonical))
    return out

def collect_knowledge(store: Path) -> list[tuple[str, bytes]]:
    store = store.expanduser().resolve()
    db = store / "knowledge.sqlite3"
    if not db.is_file():
        raise ReplicationError(f"knowledge graph is not initialized: {store}")
    out: list[tuple[str, bytes]] = []
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT sha256, canonical_json FROM documents ORDER BY sha256").fetchall()
    for digest, payload in rows:
        digest = str(digest).lower()
        if not HEX64_RE.fullmatch(digest):
            raise ReplicationError(f"invalid knowledge document digest in database: {digest}")
        try:
            doc = json.loads(str(payload))
        except json.JSONDecodeError as exc:
            raise ReplicationError(f"invalid canonical knowledge JSON for {digest}: {exc}") from exc
        canonical = canonical_json(doc)
        if sha256_bytes(canonical) != digest:
            raise ReplicationError(f"knowledge document semantic hash mismatch: {digest}")
        out.append((f"knowledge/{digest}.json", canonical))
    return out

def collect_control_history(control: Path) -> list[tuple[str, bytes]]:
    control = control.expanduser().resolve()
    state = control / "control.json"
    if not state.is_file():
        raise ReplicationError(f"control plane is not initialized: {control}")
    history = control / "history" / "history.ndjson"
    if not history.exists():
        return []
    records: list[dict[str, Any]] = []
    for n, line in enumerate(history.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplicationError(f"invalid control history line {n}: {exc}") from exc
        if not isinstance(rec, dict):
            raise ReplicationError(f"control history line {n} is not an object")
        # Strip fields that can expose host filesystem layout while preserving terminal research history.
        safe = {k: v for k, v in rec.items() if k not in {"manifest", "run_out", "log_path", "scheduler_tool"}}
        records.append(safe)
    payload = b"".join(canonical_json(rec) for rec in records)
    return [("control/history.ndjson", payload)] if payload else []

def manifest_material(manifest: dict[str, Any]) -> bytes:
    clean = {k: v for k, v in manifest.items() if k != "bundle_id"}
    return canonical_json(clean)

def build_bundle(root: Path, state: dict[str, Any], out: Path, evidence: Path | None,
                 knowledge: Path | None, control: Path | None) -> dict[str, Any]:
    generation = int(state.get("next_generation", 1))
    if generation < 1:
        raise ReplicationError("invalid next_generation in replication store")
    entries: list[tuple[str, bytes]] = []
    components: dict[str, Any] = {}
    if evidence is not None:
        ev = collect_evidence(evidence); entries.extend(ev); components["evidence"] = {"objects": len(ev)}
    if knowledge is not None:
        kg = collect_knowledge(knowledge); entries.extend(kg); components["knowledge"] = {"documents": len(kg)}
    if control is not None:
        cp = collect_control_history(control); entries.extend(cp)
        count = 0
        if cp:
            count = len([x for x in cp[0][1].splitlines() if x.strip()])
        components["control_history"] = {"records": count}
    if not components:
        raise ReplicationError("export requires at least one of --evidence, --knowledge, or --control")
    entries.sort(key=lambda x: x[0])
    listed = [{"path": name, "size": len(data), "sha256": sha256_bytes(data)} for name, data in entries]
    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "replication_api": REPLICATION_API_VERSION,
        "source_site": state["site"],
        "generation": generation,
        "created_at": now_iso(),
        "components": components,
        "files": listed,
        "policy": {
            "target_binaries_included": False,
            "live_control_state_included": False,
            "merge": "content-addressed-idempotent",
        },
    }
    manifest["bundle_id"] = sha256_bytes(manifest_material(manifest))
    out = out.expanduser().resolve(); out.parent.mkdir(parents=True, exist_ok=True)
    epoch = (2000, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, epoch); zi.create_system = 3; zi.external_attr = (0o100644 << 16)
            zf.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        zi = zipfile.ZipInfo("bundle.json", epoch); zi.create_system = 3; zi.external_attr = (0o100644 << 16)
        zf.writestr(zi, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    state["next_generation"] = generation + 1
    state["last_export"] = {"generation": generation, "bundle_id": manifest["bundle_id"], "path": str(out), "created_at": manifest["created_at"]}
    write_json(root / "replication.json", state)
    return manifest

def safe_member(name: str) -> bool:
    p = Path(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name

def verify_bundle(path: Path) -> tuple[dict[str, Any], list[str]]:
    path = path.expanduser().resolve()
    errors: list[str] = []
    if not path.is_file():
        return {}, [f"bundle does not exist: {path}"]
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        return {}, ["bundle exceeds size limit"]
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "bundle.json" not in names:
                return {}, ["bundle.json is missing"]
            if len(names) != len(set(names)):
                errors.append("bundle contains duplicate member names")
            for info in zf.infolist():
                if not safe_member(info.filename): errors.append(f"unsafe member path: {info.filename}")
                if info.file_size > MAX_MEMBER_BYTES: errors.append(f"member exceeds size limit: {info.filename}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000: errors.append(f"symlink members are forbidden: {info.filename}")
            manifest = json.loads(zf.read("bundle.json"))
            if not isinstance(manifest, dict): return {}, ["bundle manifest is not an object"]
            if manifest.get("schema") != BUNDLE_SCHEMA: errors.append(f"schema must be {BUNDLE_SCHEMA}")
            if int(manifest.get("replication_api", -1)) != REPLICATION_API_VERSION: errors.append("unsupported replication_api")
            try: validate_site(str(manifest.get("source_site", "")))
            except ReplicationError as exc: errors.append(str(exc))
            try:
                if int(manifest.get("generation", 0)) < 1: errors.append("generation must be >= 1")
            except (TypeError, ValueError): errors.append("invalid generation")
            expected_id = sha256_bytes(manifest_material(manifest))
            if manifest.get("bundle_id") != expected_id: errors.append("bundle_id mismatch")
            listed = manifest.get("files")
            if not isinstance(listed, list): listed = []; errors.append("files must be an array")
            actual_members = set(names) - {"bundle.json"}
            declared: set[str] = set()
            for item in listed:
                if not isinstance(item, dict): errors.append("invalid file manifest entry"); continue
                name = str(item.get("path", "")); declared.add(name)
                if not safe_member(name): errors.append(f"unsafe declared path: {name}"); continue
                if name not in actual_members: errors.append(f"missing member: {name}"); continue
                raw = zf.read(name)
                if len(raw) != item.get("size"): errors.append(f"size mismatch: {name}")
                if sha256_bytes(raw) != item.get("sha256"): errors.append(f"hash mismatch: {name}")
                if name.startswith(("evidence/", "knowledge/")):
                    leaf = Path(name).stem
                    if not HEX64_RE.fullmatch(leaf): errors.append(f"invalid content-addressed filename: {name}")
                    else:
                        try: canonical = canonical_json(json.loads(raw))
                        except json.JSONDecodeError: errors.append(f"invalid JSON object: {name}")
                        else:
                            if sha256_bytes(canonical) != leaf: errors.append(f"semantic hash mismatch: {name}")
            extra = sorted(actual_members - declared)
            if extra: errors.append("undeclared bundle members: " + ", ".join(extra))
            policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
            if policy.get("target_binaries_included") is not False: errors.append("bundle must declare target_binaries_included=false")
            if policy.get("live_control_state_included") is not False: errors.append("bundle must declare live_control_state_included=false")
            return manifest, errors
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError, KeyError) as exc:
        return {}, [f"cannot verify bundle: {exc}"]

def receipt_path(root: Path, site: str, generation: int) -> Path:
    return root / "receipts" / site / f"{generation:020d}.json"

def import_bundle(root: Path, bundle: Path, evidence: Path | None, knowledge: Path | None) -> dict[str, Any]:
    manifest, errors = verify_bundle(bundle)
    if errors:
        raise ReplicationError("bundle verification failed: " + "; ".join(errors))
    site = str(manifest["source_site"]); generation = int(manifest["generation"]); bundle_id = str(manifest["bundle_id"])
    receipt = receipt_path(root, site, generation)
    if receipt.exists():
        old = read_json(receipt)
        if old.get("bundle_id") != bundle_id:
            raise ReplicationError(f"replication conflict: site {site} generation {generation} already imported with different bundle_id")
        return {"schema": RECEIPT_SCHEMA, "status": "already-imported", "source_site": site, "generation": generation, "bundle_id": bundle_id,
                "evidence": old.get("evidence", {}), "knowledge": old.get("knowledge", {}), "control_history": old.get("control_history", {})}
    evidence_paths: list[Path] = []
    knowledge_paths: list[Path] = []
    history_lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ppclab-replicate-") as raw:
        td = Path(raw)
        with zipfile.ZipFile(bundle) as zf:
            for item in manifest.get("files", []):
                name = item["path"]
                data = zf.read(name)
                if name.startswith("evidence/"):
                    p = td / "evidence" / Path(name).name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); evidence_paths.append(p)
                elif name.startswith("knowledge/"):
                    p = td / "knowledge" / Path(name).name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); knowledge_paths.append(p)
                elif name == "control/history.ndjson":
                    history_lines = data.decode("utf-8").splitlines()
        ev_result: dict[str, Any] = {"objects": 0, "ingested": 0}
        if evidence_paths:
            if evidence is None: raise ReplicationError("bundle contains evidence; --evidence destination is required")
            evmod = load_module("ppclab_replication_evidence", "ppc_lab_evidence.py")
            evmod.init_store(evidence)
            result = evmod.ingest(evidence.expanduser().resolve(), evidence_paths, strict=True)
            ev_result = {"objects": len(evidence_paths), "ingested": len(result.get("artifacts", []))}
        kg_result: dict[str, Any] = {"documents": 0, "ingested": 0}
        if knowledge_paths:
            if knowledge is None: raise ReplicationError("bundle contains knowledge; --knowledge destination is required")
            kgmod = load_module("ppclab_replication_knowledge", "ppc_lab_knowledge.py")
            kgmod.init_graph(knowledge)
            result = kgmod.ingest_paths(knowledge.expanduser().resolve(), knowledge_paths)
            kg_result = {"documents": len(knowledge_paths), "ingested": int(result.get("added", 0)), "deduplicated": int(result.get("deduplicated", 0))}
    history_result = {"records": len(history_lines)}
    if history_lines:
        archive = root / "control-history" / site / f"{generation:020d}.ndjson"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("\n".join(history_lines) + "\n", encoding="utf-8")
    doc = {
        "schema": RECEIPT_SCHEMA, "replication_api": REPLICATION_API_VERSION, "status": "imported",
        "source_site": site, "generation": generation, "bundle_id": bundle_id, "bundle_sha256": sha256_file(bundle), "imported_at": now_iso(),
        "evidence": ev_result, "knowledge": kg_result, "control_history": history_result,
    }
    write_json(receipt, doc)
    return doc

def status(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for p in sorted((root / "receipts").glob("*/*.json")):
        try:
            d = read_json(p)
        except ReplicationError:
            continue
        receipts.append({"source_site": d.get("source_site"), "generation": d.get("generation"), "bundle_id": d.get("bundle_id"), "imported_at": d.get("imported_at")})
    by_site: dict[str, int] = {}
    for r in receipts:
        site = str(r.get("source_site") or "")
        try: gen = int(r.get("generation", 0))
        except (TypeError, ValueError): gen = 0
        by_site[site] = max(by_site.get(site, 0), gen)
    return {"schema": STATUS_SCHEMA, "replication_api": REPLICATION_API_VERSION, "site": state["site"], "next_generation": state["next_generation"],
            "last_export": state.get("last_export"), "imported_receipts": len(receipts), "latest_generation_by_site": dict(sorted(by_site.items()))}

def dump(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True))

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="initialize a replication site")
    p.add_argument("root", type=Path); p.add_argument("--site", required=True)
    p = sub.add_parser("export", help="create a content-addressed offline replication bundle")
    p.add_argument("root", type=Path); p.add_argument("--out", type=Path, required=True); p.add_argument("--evidence", type=Path); p.add_argument("--knowledge", type=Path); p.add_argument("--control", type=Path)
    p = sub.add_parser("verify", help="verify a replication bundle without importing it")
    p.add_argument("bundle", type=Path); p.add_argument("--json", action="store_true")
    p = sub.add_parser("import", help="merge a verified bundle into local evidence/knowledge stores")
    p.add_argument("root", type=Path); p.add_argument("bundle", type=Path); p.add_argument("--evidence", type=Path); p.add_argument("--knowledge", type=Path)
    p = sub.add_parser("status", help="show site generations and imported receipts")
    p.add_argument("root", type=Path); p.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    try:
        if ns.cmd == "init":
            root, state = ensure_store(ns.root, create=True, site=ns.site); dump({"schema": STORE_SCHEMA, "site": state["site"], "root": str(root), "next_generation": state["next_generation"]}); return 0
        if ns.cmd == "verify":
            manifest, errors = verify_bundle(ns.bundle)
            doc = {"schema": VERIFY_SCHEMA, "ok": not errors, "bundle_id": manifest.get("bundle_id") if manifest else None, "source_site": manifest.get("source_site") if manifest else None, "generation": manifest.get("generation") if manifest else None, "errors": errors}
            if ns.json: dump(doc)
            else:
                print(f"replication bundle={'PASS' if not errors else 'FAIL'} id={doc['bundle_id'] or '-'}")
                for e in errors: print("ERROR: " + e, file=sys.stderr)
            return 0 if not errors else 1
        root, state = ensure_store(ns.root)
        if ns.cmd == "export":
            manifest = build_bundle(root, state, ns.out, ns.evidence, ns.knowledge, ns.control); dump(manifest); return 0
        if ns.cmd == "import":
            dump(import_bundle(root, ns.bundle, ns.evidence, ns.knowledge)); return 0
        doc = status(root, state)
        if ns.json: dump(doc)
        else:
            print(f"site={doc['site']} next_generation={doc['next_generation']} imported_receipts={doc['imported_receipts']}")
            for site, gen in doc["latest_generation_by_site"].items(): print(f"peer.{site}.generation={gen}")
        return 0
    except (ReplicationError, OSError, ValueError, sqlite3.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ppc-lab-replicate: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
