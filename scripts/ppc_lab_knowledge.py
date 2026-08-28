#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab research knowledge graph.

This is deliberately a dependency-free SQLite relationship index over PPC Lab's
JSON research artifacts. It stores evidence/metadata, hashes, symbols, behavior
fingerprints, and relationships. It never copies target binary bytes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

GRAPH_SCHEMA_VERSION = 1
QUERY_SCHEMA = "ppc-lab-knowledge-query-v1"
REPORT_SCHEMA = "ppc-lab-knowledge-report-v1"
RELATED_SCHEMA = "ppc-lab-knowledge-related-v1"
PATH_SCHEMA = "ppc-lab-knowledge-path-v1"
EXPORT_SCHEMA = "ppc-lab-evidence-v1"
VERIFY_SCHEMA = "ppc-lab-knowledge-verify-v1"


class KnowledgeError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value)


def parse_address(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = value if isinstance(value, int) else int(str(value), 0)
    except (TypeError, ValueError):
        return None
    return f"0x{number & 0xFFFFFFFF:08x}"


def graph_db(root: Path) -> Path:
    return root / "knowledge.sqlite3"


def connect(root: Path, create: bool = False) -> sqlite3.Connection:
    root = root.expanduser().resolve()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    db = graph_db(root)
    if not db.exists() and not create:
        raise KnowledgeError(f"knowledge graph is not initialized: {root}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(
            sha256 TEXT PRIMARY KEY,
            schema_name TEXT NOT NULL,
            canonical_json TEXT NOT NULL,
            first_ingested TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_sources(
            document_sha256 TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
            source_path TEXT NOT NULL,
            raw_sha256 TEXT NOT NULL,
            raw_size INTEGER NOT NULL,
            ingested_at TEXT NOT NULL,
            PRIMARY KEY(document_sha256, source_path, raw_sha256)
        );
        CREATE TABLE IF NOT EXISTS nodes(
            node_key TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            label TEXT NOT NULL,
            target_sha256 TEXT,
            address TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS edges(
            source_key TEXT NOT NULL REFERENCES nodes(node_key) ON DELETE CASCADE,
            target_key TEXT NOT NULL REFERENCES nodes(node_key) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            document_sha256 TEXT NOT NULL REFERENCES documents(sha256) ON DELETE CASCADE,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(source_key, target_key, relation, document_sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
        CREATE INDEX IF NOT EXISTS idx_nodes_target ON nodes(target_sha256);
        CREATE INDEX IF NOT EXISTS idx_nodes_address ON nodes(address);
        CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_key);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_key);
        CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
        CREATE INDEX IF NOT EXISTS idx_docs_schema ON documents(schema_name);
        """
    )
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(GRAPH_SCHEMA_VERSION),))
    conn.commit()


def init_graph(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    with connect(root, create=True) as conn:
        init_schema(conn)
    return {"graph": str(root), "schema_version": GRAPH_SCHEMA_VERSION}


def add_node(conn: sqlite3.Connection, key: str, node_type: str, label: str,
             target_sha: str | None = None, address: str | None = None,
             metadata: dict[str, Any] | None = None) -> None:
    payload = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    conn.execute(
        """INSERT INTO nodes(node_key,node_type,label,target_sha256,address,metadata_json)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(node_key) DO UPDATE SET
             label=excluded.label,
             target_sha256=COALESCE(nodes.target_sha256,excluded.target_sha256),
             address=COALESCE(nodes.address,excluded.address),
             metadata_json=CASE WHEN nodes.metadata_json='{}' THEN excluded.metadata_json ELSE nodes.metadata_json END""",
        (key, node_type, label, target_sha, address, payload),
    )


def add_edge(conn: sqlite3.Connection, src: str, dst: str, relation: str, doc_sha: str,
             metadata: dict[str, Any] | None = None) -> None:
    payload = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    conn.execute(
        "INSERT OR IGNORE INTO edges(source_key,target_key,relation,document_sha256,metadata_json) VALUES(?,?,?,?,?)",
        (src, dst, relation, doc_sha, payload),
    )


def harvest_input_hashes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        inputs = value.get("inputs")
        if isinstance(inputs, dict):
            for item in inputs.values():
                if isinstance(item, dict) and valid_sha(item.get("sha256")):
                    found.add(str(item["sha256"]).lower())
        elif isinstance(inputs, list):
            for item in inputs:
                if isinstance(item, dict) and valid_sha(item.get("sha256")):
                    found.add(str(item["sha256"]).lower())
        provenance = value.get("input_provenance")
        if isinstance(provenance, list):
            for item in provenance:
                if isinstance(item, dict) and valid_sha(item.get("sha256")):
                    found.add(str(item["sha256"]).lower())
        if valid_sha(value.get("target_sha256")):
            found.add(str(value["target_sha256"]).lower())
        for child in value.values():
            found.update(harvest_input_hashes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(harvest_input_hashes(child))
    return found



def harvest_behavior_hashes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        digest = value.get("behavior_sha256")
        if valid_sha(digest):
            found.add(str(digest).lower())
        for child in value.values():
            found.update(harvest_behavior_hashes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(harvest_behavior_hashes(child))
    return found

def result_payload(doc: dict[str, Any]) -> dict[str, Any] | None:
    if doc.get("schema") == "ppc-lab-result-v1":
        return doc
    response = doc.get("response")
    if isinstance(response, dict) and isinstance(response.get("result"), dict):
        return response["result"]
    result = doc.get("result")
    return result if isinstance(result, dict) else None


def behavior_payload(doc: dict[str, Any]) -> dict[str, Any] | None:
    result = result_payload(doc)
    if result:
        return {
            "stop_reason": result.get("stop_reason"),
            "pc": result.get("pc"),
            "registers": result.get("registers"),
            "cr": result.get("cr"), "lr": result.get("lr"), "ctr": result.get("ctr"),
            "dumps": [{"address": x.get("address"), "size": x.get("size"), "fnv1a64": x.get("fnv1a64")}
                      for x in result.get("dumps", []) if isinstance(x, dict)],
        }
    if doc.get("schema") == "ppc-lab-corpus-case-v1":
        exp = doc.get("expectation")
        if isinstance(exp, dict):
            return exp
    return None


def scope_for(targets: set[str]) -> str:
    return next(iter(targets)) if len(targets) == 1 else "global"


def function_key(scope: str, name: str) -> str:
    clean = name.strip() or "<unknown>"
    return f"function:{scope}:{clean}"


def address_key(scope: str, address: str) -> str:
    return f"address:{scope}:{address}"

def hypothesis_key(scope: str, item: dict[str, Any]) -> str:
    material = "|".join(str(item.get(k) or "") for k in ("subject", "role", "claim"))
    return f"hypothesis:{scope}:{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def document_relations(conn: sqlite3.Connection, doc: dict[str, Any], doc_sha: str,
                       source_label: str, forced_target: str | None = None) -> dict[str, int]:
    schema = str(doc.get("schema") or "unknown-json")
    doc_key = f"document:{doc_sha}"
    add_node(conn, doc_key, "document", Path(source_label).name, metadata={"schema": schema})
    schema_key = f"schema:{schema}"
    add_node(conn, schema_key, "schema", schema)
    add_edge(conn, doc_key, schema_key, "has-schema", doc_sha)

    targets = harvest_input_hashes(doc)
    if forced_target:
        if not valid_sha(forced_target):
            raise KnowledgeError("--target-sha256 must be exactly 64 hexadecimal characters")
        targets.add(forced_target.lower())
    for target in sorted(targets):
        key = f"target:{target}"
        add_node(conn, key, "target", target[:16], target_sha=target)
        add_edge(conn, doc_key, key, "targets", doc_sha)

    scope = scope_for(targets)
    counts = {"targets": len(targets), "symbols": 0, "addresses": 0, "functions": 0, "behaviors": 0, "coverage": 0, "calls": 0, "hypotheses": 0}

    symbols = doc.get("symbols")
    if isinstance(symbols, list):
        for item in symbols:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("symbol") or "").strip()
            addr = parse_address(item.get("address") if item.get("address") is not None else item.get("value"))
            if not name and not addr:
                continue
            label = name or addr or "symbol"
            skey = f"symbol:{scope}:{addr or 'none'}:{hashlib.sha1(label.encode()).hexdigest()[:12]}"
            target_sha = None if scope == "global" else scope
            add_node(conn, skey, "symbol", label, target_sha=target_sha, address=addr, metadata=item)
            add_edge(conn, doc_key, skey, "defines-symbol", doc_sha)
            if addr:
                akey = address_key(scope, addr)
                add_node(conn, akey, "address", addr, target_sha=target_sha, address=addr)
                add_edge(conn, skey, akey, "located-at", doc_sha)
                counts["addresses"] += 1
            counts["symbols"] += 1

    if schema == "ppc-lab-trace-analysis-v1":
        for item in doc.get("functions", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "<unknown>")
            fkey = function_key(scope, name)
            target_sha = None if scope == "global" else scope
            add_node(conn, fkey, "function", name, target_sha=target_sha, metadata=item)
            add_edge(conn, doc_key, fkey, "observed-function", doc_sha, {"instructions_executed": item.get("instructions_executed")})
            counts["functions"] += 1
        for item in doc.get("hot_pcs", []):
            if not isinstance(item, dict):
                continue
            addr = parse_address(item.get("pc"))
            if not addr:
                continue
            akey = address_key(scope, addr)
            target_sha = None if scope == "global" else scope
            add_node(conn, akey, "address", addr, target_sha=target_sha, address=addr, metadata=item)
            add_edge(conn, doc_key, akey, "executed", doc_sha, {"count": item.get("count"), "disassembly": item.get("disassembly")})
            fn = str(item.get("function") or "").strip()
            if fn:
                fkey = function_key(scope, fn)
                add_node(conn, fkey, "function", fn, target_sha=target_sha)
                add_edge(conn, akey, fkey, "belongs-to-function", doc_sha)
            counts["addresses"] += 1
        for item in doc.get("calls", []):
            if not isinstance(item, dict):
                continue
            caller = str(item.get("caller") or "<unknown>")
            callee = str(item.get("callee") or "<unknown>")
            src = function_key(scope, caller); dst = function_key(scope, callee)
            target_sha = None if scope == "global" else scope
            add_node(conn, src, "function", caller, target_sha=target_sha)
            add_node(conn, dst, "function", callee, target_sha=target_sha)
            add_edge(conn, src, dst, "observed-call", doc_sha, {"site": item.get("site"), "target": item.get("target"), "count": item.get("count")})
            counts["calls"] += 1
        coverage_material = sorted(str(x.get("pc")) for x in doc.get("hot_pcs", []) if isinstance(x, dict) and x.get("pc"))
        if coverage_material:
            digest = sha256_bytes(canonical(coverage_material))
            ckey = f"coverage:{digest}"
            add_node(conn, ckey, "coverage", digest[:16], metadata={"unique_pcs": len(coverage_material)})
            add_edge(conn, doc_key, ckey, "has-coverage", doc_sha)
            counts["coverage"] += 1

    behavior_digests = harvest_behavior_hashes(doc)
    behavior = behavior_payload(doc)
    if behavior is not None:
        behavior_digests.add(sha256_bytes(canonical(behavior)))
    for digest in sorted(behavior_digests):
        bkey = f"behavior:{digest}"
        add_node(conn, bkey, "behavior", digest[:16], metadata={"fingerprint": digest})
        add_edge(conn, doc_key, bkey, "has-behavior", doc_sha)
        counts["behaviors"] += 1

    if schema == "ppc-lab-corpus-case-v1":
        case_id = str(doc.get("id") or doc_sha[:12])
        ckey = f"corpus-case:{case_id}"
        add_node(conn, ckey, "corpus-case", case_id, metadata={"description": doc.get("description"), "tags": doc.get("tags", [])})
        add_edge(conn, doc_key, ckey, "describes-case", doc_sha)
        for target in sorted(targets):
            add_edge(conn, ckey, f"target:{target}", "regresses-target", doc_sha)

    if schema == "ppc-lab-differential-triage-v1":
        tkey = f"triage:{doc_sha}"
        add_node(conn, tkey, "triage", str(doc.get("classification") or "triage"), metadata={"equal": doc.get("equal"), "classification": doc.get("classification")})
        add_edge(conn, doc_key, tkey, "describes-triage", doc_sha)
        first = doc.get("first_divergence")
        if isinstance(first, dict):
            for side in ("left", "right"):
                item = first.get(side)
                if isinstance(item, dict):
                    addr = parse_address(item.get("pc"))
                    if addr:
                        akey = address_key(scope, addr)
                        add_node(conn, akey, "address", addr, target_sha=None if scope == "global" else scope, address=addr)
                        add_edge(conn, tkey, akey, f"first-divergence-{side}", doc_sha)

    if schema == "ppc-lab-campaign-summary-v1":
        name = str(doc.get("name") or "campaign")
        manifest = str(doc.get("manifest_sha256") or doc_sha)[:16]
        ckey = f"campaign:{manifest}:{name}"
        add_node(conn, ckey, "campaign", name, metadata={"status": doc.get("status"), "engine_version": doc.get("engine_version")})
        add_edge(conn, doc_key, ckey, "describes-campaign", doc_sha)
        for target in sorted(targets):
            add_edge(conn, ckey, f"target:{target}", "researched-target", doc_sha)

    if schema in {"ppc-lab-hypothesis-report-v1", "ppc-lab-hypothesis-v1"}:
        items = doc.get("hypotheses") if schema == "ppc-lab-hypothesis-report-v1" else [doc]
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                hkey = hypothesis_key(scope, item)
                status = str(item.get("status") or "candidate")
                metadata = {k: item.get(k) for k in ("id", "subject", "role", "claim", "confidence", "status", "metrics") if item.get(k) is not None}
                add_node(conn, hkey, "hypothesis", str(item.get("claim") or item.get("subject") or "hypothesis"), target_sha=None if scope == "global" else scope, metadata=metadata)
                add_edge(conn, doc_key, hkey, "supports-hypothesis" if status == "supported" else "proposes-hypothesis", doc_sha, {"confidence": item.get("confidence"), "status": status})
                for target in sorted(targets):
                    add_edge(conn, hkey, f"target:{target}", "hypothesizes-target", doc_sha)
                for digest in item.get("supporting_behaviors", []) if isinstance(item.get("supporting_behaviors"), list) else []:
                    if valid_sha(digest):
                        bkey = f"behavior:{str(digest).lower()}"
                        add_node(conn, bkey, "behavior", str(digest)[:16], metadata={"fingerprint": str(digest).lower()})
                        add_edge(conn, hkey, bkey, "supported-by-behavior", doc_sha)
                subject = str(item.get("subject") or "")
                if subject.startswith("writes_u32.") or subject.startswith("writes_f32."):
                    addr = parse_address(subject.split(".", 1)[1])
                    if addr:
                        akey = address_key(scope, addr)
                        add_node(conn, akey, "address", addr, target_sha=None if scope == "global" else scope, address=addr)
                        add_edge(conn, hkey, akey, "hypothesizes-state-at", doc_sha, {"role": item.get("role")})
                counts["hypotheses"] += 1

    annotations = doc.get("annotations")
    if isinstance(annotations, list):
        for item in annotations:
            if not isinstance(item, dict):
                continue
            addr = parse_address(item.get("address"))
            if not addr:
                continue
            akey = address_key(scope, addr)
            add_node(conn, akey, "address", addr, target_sha=None if scope == "global" else scope, address=addr)
            add_edge(conn, doc_key, akey, "annotates", doc_sha, {"kind": item.get("kind"), "comment": item.get("comment")})

    return counts


def ingest_document(conn: sqlite3.Connection, doc: dict[str, Any], source_path: str,
                    raw_sha: str, raw_size: int, forced_target: str | None = None) -> tuple[str, bool, dict[str, int]]:
    blob = canonical(doc)
    digest = sha256_bytes(blob)
    schema = str(doc.get("schema") or "unknown-json")
    existed = conn.execute("SELECT 1 FROM documents WHERE sha256=?", (digest,)).fetchone() is not None
    conn.execute(
        "INSERT OR IGNORE INTO documents(sha256,schema_name,canonical_json,first_ingested) VALUES(?,?,?,?)",
        (digest, schema, blob.decode("utf-8"), utc_now()),
    )
    conn.execute(
        "INSERT OR IGNORE INTO document_sources(document_sha256,source_path,raw_sha256,raw_size,ingested_at) VALUES(?,?,?,?,?)",
        (digest, source_path, raw_sha, raw_size, utc_now()),
    )
    counts = document_relations(conn, doc, digest, source_path, forced_target)
    return digest, existed, counts


def candidate_files(paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path.is_dir():
            items = sorted(p for p in path.rglob("*.json") if p.is_file())
        else:
            items = [path]
        for item in items:
            if item not in seen:
                seen.add(item); yield item


def ingest_paths(root: Path, paths: list[Path], forced_target: str | None = None) -> dict[str, Any]:
    added = dedup = skipped = 0
    relation_counts: dict[str, int] = {}
    with connect(root) as conn:
        init_schema(conn)
        for path in candidate_files(paths):
            try:
                raw = path.read_bytes(); doc = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                skipped += 1; continue
            if not isinstance(doc, dict) or not str(doc.get("schema", "")).startswith("ppc-lab-"):
                skipped += 1; continue
            _, existed, counts = ingest_document(conn, doc, str(path), sha256_bytes(raw), len(raw), forced_target)
            dedup += int(existed); added += int(not existed)
            for key, value in counts.items(): relation_counts[key] = relation_counts.get(key, 0) + value
        conn.commit()
    return {"added": added, "deduplicated": dedup, "skipped": skipped, "relations": relation_counts}


def sync_evidence(root: Path, store: Path) -> dict[str, Any]:
    store = store.expanduser().resolve()
    db = store / "evidence.sqlite3"
    if not db.is_file():
        raise KnowledgeError(f"not a PPC Lab evidence store: {store}")
    edb = sqlite3.connect(db); edb.row_factory = sqlite3.Row
    try:
        rows = edb.execute("SELECT sha256 FROM artifacts ORDER BY id").fetchall()
    finally:
        edb.close()
    paths = [store / "objects" / "sha256" / row["sha256"][:2] / f"{row['sha256']}.json" for row in rows]
    result = ingest_paths(root, paths)
    result["evidence_store"] = str(store); result["indexed_artifacts"] = len(rows)
    return result


def node_row(row: sqlite3.Row) -> dict[str, Any]:
    return {"key": row["node_key"], "type": row["node_type"], "label": row["label"],
            "target_sha256": row["target_sha256"], "address": row["address"],
            "metadata": json.loads(row["metadata_json"] or "{}")}


def resolve_node(conn: sqlite3.Connection, value: str) -> str:
    exact = conn.execute("SELECT node_key FROM nodes WHERE node_key=?", (value,)).fetchall()
    if len(exact) == 1: return exact[0][0]
    rows = conn.execute("SELECT node_key FROM nodes WHERE node_key LIKE ? ORDER BY node_key LIMIT 3", (value + "%",)).fetchall()
    if len(rows) == 1: return rows[0][0]
    if not rows: raise KnowledgeError(f"node not found: {value}")
    raise KnowledgeError(f"node reference is ambiguous: {value}")


def query_graph(root: Path, ns: argparse.Namespace) -> dict[str, Any]:
    clauses=[]; args: list[Any]=[]
    if ns.type: clauses.append("node_type=?"); args.append(ns.type)
    if ns.label: clauses.append("label LIKE ?"); args.append(f"%{ns.label}%")
    if ns.target_sha256: clauses.append("target_sha256 LIKE ?"); args.append(ns.target_sha256.lower()+"%")
    if ns.address:
        addr=parse_address(ns.address)
        if not addr: raise KnowledgeError("invalid --address")
        clauses.append("address=?"); args.append(addr)
    sql="SELECT * FROM nodes" + ((" WHERE "+" AND ".join(clauses)) if clauses else "") + " ORDER BY node_type,label,node_key LIMIT ?"
    args.append(ns.limit)
    with connect(root) as conn:
        rows=[node_row(x) for x in conn.execute(sql,args)]
        if ns.relation:
            keep=[]
            for item in rows:
                hit=conn.execute("SELECT 1 FROM edges WHERE (source_key=? OR target_key=?) AND relation=? LIMIT 1",(item["key"],item["key"],ns.relation)).fetchone()
                if hit: keep.append(item)
            rows=keep
    return {"schema":QUERY_SCHEMA,"count":len(rows),"results":rows}


def related_graph(root: Path, ref: str, depth: int, relation: str | None) -> dict[str, Any]:
    with connect(root) as conn:
        start=resolve_node(conn,ref); seen={start:0}; q=deque([start]); edges=[]
        while q:
            cur=q.popleft(); d=seen[cur]
            if d>=depth: continue
            sql="SELECT * FROM edges WHERE (source_key=? OR target_key=?)"; args:[Any]=[cur,cur]
            if relation: sql += " AND relation=?"; args.append(relation)
            for row in conn.execute(sql,args):
                nxt=row["target_key"] if row["source_key"]==cur else row["source_key"]
                edges.append({"source":row["source_key"],"target":row["target_key"],"relation":row["relation"],"document_sha256":row["document_sha256"]})
                if nxt not in seen:
                    seen[nxt]=d+1; q.append(nxt)
        nodes=[]
        for key,d in sorted(seen.items(),key=lambda x:(x[1],x[0])):
            row=conn.execute("SELECT * FROM nodes WHERE node_key=?",(key,)).fetchone(); item=node_row(row); item["depth"]=d; nodes.append(item)
    unique_edges={(e["source"],e["target"],e["relation"],e["document_sha256"]):e for e in edges}
    return {"schema":RELATED_SCHEMA,"start":start,"depth":depth,"nodes":nodes,"edges":list(unique_edges.values())}


def shortest_path(root: Path, src_ref: str, dst_ref: str, max_depth: int) -> dict[str, Any]:
    with connect(root) as conn:
        src=resolve_node(conn,src_ref); dst=resolve_node(conn,dst_ref)
        q=deque([src]); prev={src:None}; prev_edge={}
        while q and dst not in prev:
            cur=q.popleft(); depth=0; p=cur
            while prev[p] is not None: depth+=1; p=prev[p]
            if depth>=max_depth: continue
            for row in conn.execute("SELECT * FROM edges WHERE source_key=? OR target_key=?",(cur,cur)):
                nxt=row["target_key"] if row["source_key"]==cur else row["source_key"]
                if nxt in prev: continue
                prev[nxt]=cur; prev_edge[nxt]={"source":row["source_key"],"target":row["target_key"],"relation":row["relation"],"document_sha256":row["document_sha256"]}; q.append(nxt)
        if dst not in prev:
            return {"schema":PATH_SCHEMA,"found":False,"source":src,"target":dst,"nodes":[],"edges":[]}
        chain=[]; edge_chain=[]; cur=dst
        while cur is not None:
            chain.append(cur)
            if cur in prev_edge: edge_chain.append(prev_edge[cur])
            cur=prev[cur]
        chain.reverse(); edge_chain.reverse()
        nodes=[node_row(conn.execute("SELECT * FROM nodes WHERE node_key=?",(k,)).fetchone()) for k in chain]
    return {"schema":PATH_SCHEMA,"found":True,"source":src,"target":dst,"nodes":nodes,"edges":edge_chain}


def report_graph(root: Path) -> dict[str, Any]:
    with connect(root) as conn:
        node_counts={r["node_type"]:r["n"] for r in conn.execute("SELECT node_type,COUNT(*) n FROM nodes GROUP BY node_type ORDER BY node_type")}
        rel_counts={r["relation"]:r["n"] for r in conn.execute("SELECT relation,COUNT(*) n FROM edges GROUP BY relation ORDER BY relation")}
        schemas={r["schema_name"]:r["n"] for r in conn.execute("SELECT schema_name,COUNT(*) n FROM documents GROUP BY schema_name ORDER BY schema_name")}
        docs=conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]; edges=conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        targets=conn.execute("SELECT COUNT(*) FROM nodes WHERE node_type='target'").fetchone()[0]
    return {"schema":REPORT_SCHEMA,"documents":docs,"nodes":sum(node_counts.values()),"edges":edges,"targets":targets,"node_types":node_counts,"relations":rel_counts,"document_schemas":schemas}


def docs_for_target(conn: sqlite3.Connection, target_sha: str) -> list[dict[str, Any]]:
    tkey=f"target:{target_sha}"
    shas={r[0] for r in conn.execute("SELECT document_sha256 FROM edges WHERE (source_key=? OR target_key=?)",(tkey,tkey))}
    # Include documents connected to target-scoped nodes even when the document itself lacked explicit target provenance.
    for row in conn.execute("SELECT node_key FROM nodes WHERE target_sha256=?",(target_sha,)):
        for e in conn.execute("SELECT document_sha256 FROM edges WHERE source_key=? OR target_key=?",(row[0],row[0])): shas.add(e[0])
    out=[]
    for sha in sorted(shas):
        row=conn.execute("SELECT canonical_json FROM documents WHERE sha256=?",(sha,)).fetchone()
        if row: out.append(json.loads(row[0]))
    return out


def export_decompiler(root: Path, target_prefix: str) -> dict[str, Any]:
    with connect(root) as conn:
        rows=conn.execute("SELECT target_sha256 FROM nodes WHERE node_type='target' AND target_sha256 LIKE ? ORDER BY target_sha256",(target_prefix.lower()+"%",)).fetchall()
        if len(rows)!=1:
            raise KnowledgeError("target hash prefix must resolve to exactly one target")
        target=rows[0][0]; docs=docs_for_target(conn,target)
        symbols={}; annotations=[]; seen_ann=set()
        for doc in docs:
            for item in doc.get("symbols",[]) if isinstance(doc.get("symbols"),list) else []:
                if not isinstance(item,dict): continue
                addr=parse_address(item.get("address") if item.get("address") is not None else item.get("value")); name=item.get("name") or item.get("symbol")
                if addr and name: symbols[(addr,str(name))]={"address":addr,"name":str(name)}
            schema=doc.get("schema")
            if schema=="ppc-lab-trace-analysis-v1":
                for item in doc.get("hot_pcs",[])[:128]:
                    if not isinstance(item,dict): continue
                    addr=parse_address(item.get("pc"));
                    if addr:
                        ann=(addr,"execution",f"PPC Lab graph: executed {item.get('count',0)}x; {item.get('disassembly','')}; function={item.get('function','')}")
                        if ann not in seen_ann: seen_ann.add(ann); annotations.append({"address":ann[0],"kind":ann[1],"comment":ann[2]})
                for item in doc.get("calls",[])[:128]:
                    if not isinstance(item,dict): continue
                    addr=parse_address(item.get("site"))
                    if addr:
                        ann=(addr,"observed-call",f"PPC Lab graph: observed call {item.get('caller')} -> {item.get('callee')} {item.get('count',0)}x; target={item.get('target')}")
                        if ann not in seen_ann: seen_ann.add(ann); annotations.append({"address":ann[0],"kind":ann[1],"comment":ann[2]})
            if schema=="ppc-lab-differential-triage-v1" and not doc.get("equal",True):
                first=doc.get("first_divergence")
                if isinstance(first,dict):
                    for side in ("left","right"):
                        item=first.get(side)
                        if isinstance(item,dict):
                            addr=parse_address(item.get("pc"))
                            if addr:
                                ann=(addr,"differential-divergence",f"PPC Lab graph: {doc.get('classification')} first divergence ({side})")
                                if ann not in seen_ann: seen_ann.add(ann); annotations.append({"address":ann[0],"kind":ann[1],"comment":ann[2]})
            if schema == "ppc-lab-hypothesis-v1" and doc.get("status") == "supported":
                subject = str(doc.get("subject") or "")
                if subject.startswith("writes_u32.") or subject.startswith("writes_f32."):
                    addr = parse_address(subject.split(".", 1)[1])
                    if addr:
                        comment = f"PPC Lab hypothesis ({doc.get('confidence',0):.3f}): {doc.get('claim','')}"
                        ann=(addr,"supported-hypothesis",comment)
                        if ann not in seen_ann: seen_ann.add(ann); annotations.append({"address":ann[0],"kind":ann[1],"comment":ann[2]})
            if isinstance(doc.get("annotations"),list):
                for item in doc["annotations"]:
                    if not isinstance(item,dict): continue
                    addr=parse_address(item.get("address")); kind=str(item.get("kind") or "knowledge"); comment=str(item.get("comment") or "")
                    if addr and comment:
                        ann=(addr,kind,comment)
                        if ann not in seen_ann: seen_ann.add(ann); annotations.append({"address":addr,"kind":kind,"comment":comment})
        return {"schema":EXPORT_SCHEMA,"target_sha256":target,"format":"knowledge-graph-aggregate","entry":None,"symbols":sorted(symbols.values(),key=lambda x:(int(x["address"],0),x["name"])),"annotations":sorted(annotations,key=lambda x:(int(x["address"],0),x["kind"],x["comment"]))}


def verify_graph(root: Path) -> dict[str, Any]:
    corrupt=[]
    with connect(root) as conn:
        integrity=conn.execute("PRAGMA integrity_check").fetchone()[0]
        for row in conn.execute("SELECT sha256,canonical_json FROM documents"):
            try: doc=json.loads(row["canonical_json"]); actual=sha256_bytes(canonical(doc))
            except Exception: actual="invalid-json"
            if actual!=row["sha256"]: corrupt.append(row["sha256"])
        dangling=conn.execute("""SELECT COUNT(*) FROM edges e LEFT JOIN nodes s ON s.node_key=e.source_key LEFT JOIN nodes t ON t.node_key=e.target_key LEFT JOIN documents d ON d.sha256=e.document_sha256 WHERE s.node_key IS NULL OR t.node_key IS NULL OR d.sha256 IS NULL""").fetchone()[0]
        docs=conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    ok=integrity=="ok" and not corrupt and dangling==0
    return {"schema":VERIFY_SCHEMA,"ok":ok,"sqlite_integrity":integrity,"documents":docs,"corrupt_documents":corrupt,"dangling_edges":dangling}


def print_doc(doc: dict[str, Any], as_json: bool=True) -> None:
    if as_json: print(json.dumps(doc,indent=2,sort_keys=True))
    else: print(doc)


def main() -> int:
    ap=argparse.ArgumentParser(prog="ppc-lab-knowledge",description="PPC Lab accumulated research knowledge graph")
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("init"); p.add_argument("graph",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("ingest"); p.add_argument("graph",type=Path); p.add_argument("paths",type=Path,nargs="+"); p.add_argument("--target-sha256"); p.add_argument("--json",action="store_true")
    p=sub.add_parser("sync-evidence"); p.add_argument("graph",type=Path); p.add_argument("evidence_store",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("query"); p.add_argument("graph",type=Path); p.add_argument("--type"); p.add_argument("--label"); p.add_argument("--target-sha256"); p.add_argument("--address"); p.add_argument("--relation"); p.add_argument("--limit",type=int,default=100); p.add_argument("--json",action="store_true")
    p=sub.add_parser("related"); p.add_argument("graph",type=Path); p.add_argument("node"); p.add_argument("--depth",type=int,default=2); p.add_argument("--relation"); p.add_argument("--json",action="store_true")
    p=sub.add_parser("path"); p.add_argument("graph",type=Path); p.add_argument("source"); p.add_argument("target"); p.add_argument("--max-depth",type=int,default=8); p.add_argument("--json",action="store_true")
    p=sub.add_parser("report"); p.add_argument("graph",type=Path); p.add_argument("--json",action="store_true")
    p=sub.add_parser("export-decompiler"); p.add_argument("graph",type=Path); p.add_argument("--target-sha256",required=True); p.add_argument("--json",type=Path,required=True)
    p=sub.add_parser("verify"); p.add_argument("graph",type=Path); p.add_argument("--json",action="store_true")
    ns=ap.parse_args()
    try:
        if ns.cmd=="init": doc=init_graph(ns.graph); print_doc(doc,True); return 0
        if ns.cmd=="ingest": doc=ingest_paths(ns.graph,ns.paths,ns.target_sha256); print_doc(doc,True); return 0
        if ns.cmd=="sync-evidence": doc=sync_evidence(ns.graph,ns.evidence_store); print_doc(doc,True); return 0
        if ns.cmd=="query": doc=query_graph(ns.graph,ns); print_doc(doc,True); return 0
        if ns.cmd=="related": doc=related_graph(ns.graph,ns.node,max(0,ns.depth),ns.relation); print_doc(doc,True); return 0
        if ns.cmd=="path": doc=shortest_path(ns.graph,ns.source,ns.target,max(1,ns.max_depth)); print_doc(doc,True); return 0 if doc["found"] else 1
        if ns.cmd=="report": doc=report_graph(ns.graph); print_doc(doc,True); return 0
        if ns.cmd=="export-decompiler": doc=export_decompiler(ns.graph,ns.target_sha256); ns.json.parent.mkdir(parents=True,exist_ok=True); ns.json.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(f"exported {len(doc['symbols'])} symbols and {len(doc['annotations'])} annotations to {ns.json}"); return 0
        if ns.cmd=="verify": doc=verify_graph(ns.graph); print_doc(doc,True); return 0 if doc["ok"] else 1
    except (KnowledgeError,sqlite3.Error,OSError,json.JSONDecodeError) as exc:
        print(f"error: {exc}",file=sys.stderr); return 2
    return 2


if __name__=="__main__":
    raise SystemExit(main())
