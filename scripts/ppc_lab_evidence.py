#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab evidence store: content-addressed JSON evidence + SQLite index.

The store intentionally captures PPC Lab evidence documents, not target binaries.
Input binaries are represented by the hashes already present in orchestration/fleet
records unless a future explicit archival workflow is added.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

STORE_SCHEMA_VERSION = 1
QUERY_SCHEMA = "ppc-lab-evidence-query-v1"
REPORT_SCHEMA = "ppc-lab-evidence-report-v1"
VERIFY_SCHEMA = "ppc-lab-evidence-verify-v1"
PPC_PREFIX = "ppc-lab-"


class EvidenceError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _db_path(store: Path) -> Path:
    return store / "evidence.sqlite3"


def _object_path(store: Path, sha256: str) -> Path:
    return store / "objects" / "sha256" / sha256[:2] / f"{sha256}.json"


def _connect(store: Path, create: bool = False) -> sqlite3.Connection:
    store = store.expanduser().resolve()
    if create:
        store.mkdir(parents=True, exist_ok=True)
    db = _db_path(store)
    if not db.exists() and not create:
        raise EvidenceError(f"evidence store is not initialized: {store}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            schema_name TEXT NOT NULL,
            canonical_size INTEGER NOT NULL,
            first_ingested TEXT NOT NULL,
            name TEXT,
            job_id TEXT,
            engine_version TEXT,
            backend TEXT,
            stop_reason TEXT,
            ok INTEGER,
            exit_code INTEGER,
            host TEXT,
            cache_key TEXT,
            instructions INTEGER,
            pc TEXT
        );
        CREATE TABLE IF NOT EXISTS sources (
            artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            source_path TEXT NOT NULL,
            raw_sha256 TEXT NOT NULL,
            raw_size INTEGER NOT NULL,
            ingested_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, source_path, raw_sha256)
        );
        CREATE TABLE IF NOT EXISTS inputs (
            artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            logical_path TEXT,
            sha256 TEXT NOT NULL,
            size INTEGER,
            PRIMARY KEY (artifact_id, field_name, sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_artifacts_schema ON artifacts(schema_name);
        CREATE INDEX IF NOT EXISTS idx_artifacts_engine ON artifacts(engine_version);
        CREATE INDEX IF NOT EXISTS idx_artifacts_backend ON artifacts(backend);
        CREATE INDEX IF NOT EXISTS idx_artifacts_ok ON artifacts(ok);
        CREATE INDEX IF NOT EXISTS idx_artifacts_host ON artifacts(host);
        CREATE INDEX IF NOT EXISTS idx_artifacts_cache_key ON artifacts(cache_key);
        CREATE INDEX IF NOT EXISTS idx_inputs_sha ON inputs(sha256);
        """
    )
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(STORE_SCHEMA_VERSION),))
    conn.commit()


def init_store(store: Path) -> dict[str, Any]:
    store = store.expanduser().resolve()
    with _connect(store, create=True) as conn:
        _init_schema(conn)
    (store / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
    return {"store": str(store), "schema_version": STORE_SCHEMA_VERSION}


def _nested_result(doc: dict[str, Any]) -> dict[str, Any] | None:
    if doc.get("schema") == "ppc-lab-result-v1":
        return doc
    response = doc.get("response")
    if isinstance(response, dict):
        result = response.get("result")
        if isinstance(result, dict) and result.get("schema") == "ppc-lab-result-v1":
            return result
    result = doc.get("result")
    if isinstance(result, dict) and result.get("schema") == "ppc-lab-result-v1":
        return result
    return None


def _nested_snapshot(doc: dict[str, Any]) -> dict[str, Any] | None:
    if doc.get("schema") == "ppc-lab-snapshot-v1":
        return doc
    response = doc.get("response")
    if isinstance(response, dict):
        snap = response.get("snapshot")
        if isinstance(snap, dict) and snap.get("schema") == "ppc-lab-snapshot-v1":
            return snap
    snap = doc.get("snapshot")
    if isinstance(snap, dict) and snap.get("schema") == "ppc-lab-snapshot-v1":
        return snap
    return None


def _extract_inputs(doc: dict[str, Any]) -> list[tuple[str, str | None, str, int | None]]:
    found: dict[tuple[str, str], tuple[str, str | None, str, int | None]] = {}

    def harvest(value: Any) -> None:
        if not isinstance(value, dict):
            return
        inputs = value.get("inputs")
        if isinstance(inputs, dict):
            for field, item in inputs.items():
                if not isinstance(item, dict):
                    continue
                digest = item.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    continue
                logical = item.get("logical_path")
                if logical is not None and not isinstance(logical, str):
                    logical = str(logical)
                size = item.get("size") if isinstance(item.get("size"), int) else None
                found[(str(field), digest)] = (str(field), logical, digest.lower(), size)
        response = value.get("response")
        if isinstance(response, dict):
            harvest(response)

    harvest(doc)
    return list(found.values())


def _extract_fields(doc: dict[str, Any]) -> dict[str, Any]:
    result = _nested_result(doc) or {}
    response = doc.get("response") if isinstance(doc.get("response"), dict) else {}
    snapshot = _nested_snapshot(doc) or {}
    schema = str(doc.get("schema", ""))

    engine_version = doc.get("engine_version")
    if not isinstance(engine_version, str):
        engine = doc.get("engine")
        if isinstance(engine, dict) and isinstance(engine.get("version"), str):
            engine_version = engine["version"]
        elif isinstance(response.get("engine_version"), str):
            engine_version = response["engine_version"]
        elif isinstance(snapshot.get("engine_version"), str):
            engine_version = snapshot["engine_version"]
        else:
            engine_version = None

    ok = response.get("ok") if response else doc.get("ok")
    if not isinstance(ok, bool):
        ok = None
    exit_code = response.get("exit_code") if response else doc.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = None

    name = doc.get("name")
    if not isinstance(name, str):
        name = None
    job_id = doc.get("id")
    if not isinstance(job_id, str):
        if isinstance(response.get("id"), str):
            job_id = response["id"]
        else:
            job_id = None

    backend = result.get("backend") if isinstance(result.get("backend"), str) else doc.get("backend")
    if not isinstance(backend, str):
        backend = snapshot.get("backend") if isinstance(snapshot.get("backend"), str) else None
    stop_reason = result.get("stop_reason") if isinstance(result.get("stop_reason"), str) else doc.get("stop_reason")
    if not isinstance(stop_reason, str):
        stop_reason = snapshot.get("stop_reason") if isinstance(snapshot.get("stop_reason"), str) else None
    instructions = result.get("instructions") if isinstance(result.get("instructions"), int) else doc.get("instructions")
    if not isinstance(instructions, int) or isinstance(instructions, bool):
        instructions = snapshot.get("instructions") if isinstance(snapshot.get("instructions"), int) else None
    pc = result.get("pc") if isinstance(result.get("pc"), str) else doc.get("pc")
    if not isinstance(pc, str):
        pc = snapshot.get("pc") if isinstance(snapshot.get("pc"), str) else None

    host = doc.get("host") if isinstance(doc.get("host"), str) else None
    cache_key = doc.get("cache_key") if isinstance(doc.get("cache_key"), str) else None
    return {
        "schema_name": schema,
        "name": name,
        "job_id": job_id,
        "engine_version": engine_version,
        "backend": backend,
        "stop_reason": stop_reason,
        "ok": None if ok is None else int(ok),
        "exit_code": exit_code,
        "host": host,
        "cache_key": cache_key,
        "instructions": instructions,
        "pc": pc,
    }


def _candidate_files(paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for value in paths:
        path = value.expanduser().resolve()
        if not path.exists():
            raise EvidenceError(f"input does not exist: {path}")
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(path.rglob("*.json"))
        else:
            continue
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def ingest(store: Path, paths: Iterable[Path], strict: bool = False) -> dict[str, Any]:
    store = store.expanduser().resolve()
    init_store(store)
    added = deduplicated = skipped = malformed = 0
    artifact_ids: list[int] = []
    with _connect(store) as conn:
        for path in _candidate_files(paths):
            try:
                raw = path.read_bytes()
                doc = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                malformed += 1
                if strict:
                    raise EvidenceError(f"cannot parse JSON {path}: {exc}") from exc
                continue
            if not isinstance(doc, dict) or not isinstance(doc.get("schema"), str) or not doc["schema"].startswith(PPC_PREFIX):
                skipped += 1
                if strict:
                    raise EvidenceError(f"not a PPC Lab evidence document: {path}")
                continue
            canonical = _canonical(doc)
            semantic_sha = _sha256(canonical)
            raw_sha = _sha256(raw)
            fields = _extract_fields(doc)
            now = _utc_now()
            existing = conn.execute("SELECT id FROM artifacts WHERE sha256=?", (semantic_sha,)).fetchone()
            if existing is None:
                cur = conn.execute(
                    """INSERT INTO artifacts(sha256,schema_name,canonical_size,first_ingested,name,job_id,engine_version,backend,stop_reason,ok,exit_code,host,cache_key,instructions,pc)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (semantic_sha, fields["schema_name"], len(canonical), now, fields["name"], fields["job_id"],
                     fields["engine_version"], fields["backend"], fields["stop_reason"], fields["ok"], fields["exit_code"],
                     fields["host"], fields["cache_key"], fields["instructions"], fields["pc"]),
                )
                artifact_id = int(cur.lastrowid)
                _atomic_bytes(_object_path(store, semantic_sha), canonical)
                for field_name, logical_path, digest, size in _extract_inputs(doc):
                    conn.execute(
                        "INSERT OR IGNORE INTO inputs(artifact_id,field_name,logical_path,sha256,size) VALUES(?,?,?,?,?)",
                        (artifact_id, field_name, logical_path, digest, size),
                    )
                added += 1
            else:
                artifact_id = int(existing["id"])
                deduplicated += 1
            conn.execute(
                "INSERT OR IGNORE INTO sources(artifact_id,source_path,raw_sha256,raw_size,ingested_at) VALUES(?,?,?,?,?)",
                (artifact_id, str(path), raw_sha, len(raw), now),
            )
            artifact_ids.append(artifact_id)
        conn.commit()
    return {
        "store": str(store),
        "added": added,
        "deduplicated": deduplicated,
        "skipped": skipped,
        "malformed": malformed,
        "artifacts": artifact_ids,
    }


def _artifact_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "sha256": row["sha256"], "schema": row["schema_name"],
        "name": row["name"], "job_id": row["job_id"], "engine_version": row["engine_version"],
        "backend": row["backend"], "stop_reason": row["stop_reason"],
        "ok": None if row["ok"] is None else bool(row["ok"]), "exit_code": row["exit_code"],
        "host": row["host"], "cache_key": row["cache_key"], "instructions": row["instructions"],
        "pc": row["pc"], "first_ingested": row["first_ingested"], "canonical_size": row["canonical_size"],
    }


def query(store: Path, args: argparse.Namespace) -> dict[str, Any]:
    clauses: list[str] = []
    values: list[Any] = []
    joins = ""
    if args.schema:
        clauses.append("a.schema_name = ?"); values.append(args.schema)
    if args.engine_version:
        clauses.append("a.engine_version = ?"); values.append(args.engine_version)
    if args.backend:
        clauses.append("a.backend = ?"); values.append(args.backend)
    if args.stop_reason:
        clauses.append("a.stop_reason = ?"); values.append(args.stop_reason)
    if args.host:
        clauses.append("a.host = ?"); values.append(args.host)
    if args.name:
        clauses.append("a.name LIKE ? ESCAPE '\\'"); values.append("%" + args.name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if args.cache_key:
        clauses.append("a.cache_key LIKE ?"); values.append(args.cache_key + "%")
    if args.ok is not None:
        clauses.append("a.ok = ?"); values.append(1 if args.ok == "yes" else 0)
    if args.input_sha256:
        joins = " JOIN inputs i ON i.artifact_id=a.id "
        clauses.append("i.sha256 LIKE ?"); values.append(args.input_sha256.lower() + "%")
    sql = "SELECT DISTINCT a.* FROM artifacts a" + joins
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY a.id " + ("ASC" if args.oldest else "DESC") + " LIMIT ?"
    values.append(args.limit)
    with _connect(store) as conn:
        rows = [_artifact_row(row) for row in conn.execute(sql, values)]
    return {"schema": QUERY_SCHEMA, "store": str(store.expanduser().resolve()), "count": len(rows), "results": rows}


def _resolve_ref(conn: sqlite3.Connection, ref: str) -> sqlite3.Row:
    if ref.isdigit():
        row = conn.execute("SELECT * FROM artifacts WHERE id=?", (int(ref),)).fetchone()
        if row is not None:
            return row
    if len(ref) < 8 or any(ch not in "0123456789abcdefABCDEF" for ch in ref):
        raise EvidenceError("artifact reference must be an integer id or SHA-256 prefix of at least 8 hex characters")
    rows = conn.execute("SELECT * FROM artifacts WHERE sha256 LIKE ? ORDER BY id", (ref.lower() + "%",)).fetchall()
    if not rows:
        raise EvidenceError(f"artifact not found: {ref}")
    if len(rows) != 1:
        raise EvidenceError(f"ambiguous artifact SHA prefix: {ref}")
    return rows[0]


def show(store: Path, ref: str, metadata: bool = False) -> Any:
    with _connect(store) as conn:
        row = _resolve_ref(conn, ref)
        if metadata:
            value = _artifact_row(row)
            value["sources"] = [dict(r) for r in conn.execute(
                "SELECT source_path,raw_sha256,raw_size,ingested_at FROM sources WHERE artifact_id=? ORDER BY source_path", (row["id"],))]
            value["inputs"] = [dict(r) for r in conn.execute(
                "SELECT field_name,logical_path,sha256,size FROM inputs WHERE artifact_id=? ORDER BY field_name", (row["id"],))]
            return value
        path = _object_path(store.expanduser().resolve(), row["sha256"])
        if not path.is_file():
            raise EvidenceError(f"object missing from store: {path}")
        return json.loads(path.read_text(encoding="utf-8"))


def report(store: Path) -> dict[str, Any]:
    with _connect(store) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
        sources = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        input_hashes = int(conn.execute("SELECT COUNT(DISTINCT sha256) FROM inputs").fetchone()[0])
        def counts(column: str) -> dict[str, int]:
            rows = conn.execute(f"SELECT {column}, COUNT(*) c FROM artifacts WHERE {column} IS NOT NULL GROUP BY {column} ORDER BY c DESC, {column}")
            return {str(row[0]): int(row[1]) for row in rows}
        success = {"true": 0, "false": 0, "unknown": 0}
        for row in conn.execute("SELECT ok,COUNT(*) c FROM artifacts GROUP BY ok"):
            key = "unknown" if row[0] is None else "true" if row[0] else "false"
            success[key] = int(row[1])
        bytes_total = int(conn.execute("SELECT COALESCE(SUM(canonical_size),0) FROM artifacts").fetchone()[0])
        schema_counts = counts("schema_name")
        engine_counts = counts("engine_version")
        backend_counts = counts("backend")
        host_counts = counts("host")
        stop_counts = counts("stop_reason")
    return {
        "schema": REPORT_SCHEMA, "store": str(store.expanduser().resolve()), "schema_version": STORE_SCHEMA_VERSION,
        "artifacts": total, "sources": sources, "unique_input_hashes": input_hashes, "canonical_bytes": bytes_total,
        "success": success, "schemas": schema_counts, "engine_versions": engine_counts,
        "backends": backend_counts, "hosts": host_counts, "stop_reasons": stop_counts,
    }


def verify(store: Path) -> dict[str, Any]:
    store = store.expanduser().resolve()
    missing: list[str] = []
    corrupt: list[str] = []
    orphan: list[str] = []
    with _connect(store) as conn:
        db_rows = {row["sha256"]: int(row["canonical_size"]) for row in conn.execute("SELECT sha256,canonical_size FROM artifacts")}
        meta = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if meta is None or int(meta[0]) != STORE_SCHEMA_VERSION:
            raise EvidenceError("unsupported or missing evidence-store schema version")
    for digest, expected_size in db_rows.items():
        path = _object_path(store, digest)
        if not path.is_file():
            missing.append(digest); continue
        data = path.read_bytes()
        if len(data) != expected_size or _sha256(data) != digest:
            corrupt.append(digest)
    object_root = store / "objects" / "sha256"
    if object_root.exists():
        for path in object_root.rglob("*.json"):
            name = path.stem.lower()
            if len(name) == 64 and name not in db_rows:
                orphan.append(str(path.relative_to(store)))
    return {
        "schema": VERIFY_SCHEMA, "store": str(store), "ok": not missing and not corrupt,
        "artifacts": len(db_rows), "missing": missing, "corrupt": corrupt, "orphans": orphan,
    }


def _print_query_human(value: dict[str, Any]) -> None:
    for row in value["results"]:
        bits = [str(row["id"]), row["sha256"][:12], row["schema"]]
        if row.get("name"): bits.append(f"name={row['name']}")
        if row.get("engine_version"): bits.append(f"engine={row['engine_version']}")
        if row.get("backend"): bits.append(f"backend={row['backend']}")
        if row.get("ok") is not None: bits.append("ok=" + ("yes" if row["ok"] else "no"))
        if row.get("host"): bits.append(f"host={row['host']}")
        if row.get("stop_reason"): bits.append(f"stop={row['stop_reason']}")
        print(" ".join(bits))
    print(f"count={value['count']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="PPC Lab content-addressed evidence store")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="initialize an evidence store")
    p_init.add_argument("store", type=Path)
    p_ingest = sub.add_parser("ingest", help="ingest PPC Lab JSON files or result directories")
    p_ingest.add_argument("store", type=Path); p_ingest.add_argument("paths", nargs="+", type=Path)
    p_ingest.add_argument("--strict", action="store_true", help="fail on malformed/non-PPC-Lab JSON")
    p_ingest.add_argument("--json", action="store_true")
    p_query = sub.add_parser("query", help="query indexed evidence")
    p_query.add_argument("store", type=Path); p_query.add_argument("--schema"); p_query.add_argument("--engine-version")
    p_query.add_argument("--backend"); p_query.add_argument("--stop-reason"); p_query.add_argument("--host")
    p_query.add_argument("--name"); p_query.add_argument("--cache-key"); p_query.add_argument("--input-sha256")
    p_query.add_argument("--ok", choices=["yes", "no"]); p_query.add_argument("--limit", type=int, default=50)
    p_query.add_argument("--oldest", action="store_true"); p_query.add_argument("--json", action="store_true")
    p_show = sub.add_parser("show", help="show one artifact by id or SHA prefix")
    p_show.add_argument("store", type=Path); p_show.add_argument("ref"); p_show.add_argument("--metadata", action="store_true")
    p_report = sub.add_parser("report", help="summarize store contents")
    p_report.add_argument("store", type=Path); p_report.add_argument("--json", action="store_true")
    p_verify = sub.add_parser("verify", help="verify object hashes/database references")
    p_verify.add_argument("store", type=Path); p_verify.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if getattr(args, "limit", 1) < 1:
        parser.error("--limit must be at least 1")
    try:
        if args.command == "init":
            value = init_store(args.store); print(f"initialized {value['store']} schema={value['schema_version']}")
        elif args.command == "ingest":
            value = ingest(args.store, args.paths, strict=args.strict)
            if args.json: print(json.dumps(value, sort_keys=True, indent=2))
            else: print("added={added} deduplicated={deduplicated} skipped={skipped} malformed={malformed}".format(**value))
        elif args.command == "query":
            value = query(args.store, args)
            if args.json: print(json.dumps(value, sort_keys=True, indent=2))
            else: _print_query_human(value)
        elif args.command == "show":
            print(json.dumps(show(args.store, args.ref, metadata=args.metadata), sort_keys=True, indent=2))
        elif args.command == "report":
            value = report(args.store)
            if args.json: print(json.dumps(value, sort_keys=True, indent=2))
            else:
                print(f"artifacts={value['artifacts']} sources={value['sources']} unique_input_hashes={value['unique_input_hashes']} bytes={value['canonical_bytes']}")
                print("success=" + ",".join(f"{k}:{v}" for k,v in value["success"].items()))
                print("schemas=" + ",".join(f"{k}:{v}" for k,v in value["schemas"].items()))
        elif args.command == "verify":
            value = verify(args.store)
            if args.json: print(json.dumps(value, sort_keys=True, indent=2))
            else: print(f"ok={'yes' if value['ok'] else 'no'} artifacts={value['artifacts']} missing={len(value['missing'])} corrupt={len(value['corrupt'])} orphans={len(value['orphans'])}")
            return 0 if value["ok"] else 1
        return 0
    except EvidenceError as exc:
        print(f"ppc-lab-evidence: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"ppc-lab-evidence: database error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
