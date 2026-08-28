#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv[1]).resolve()
EVIDENCE = ROOT / "scripts" / "ppc_lab_evidence.py"
ORCH = ROOT / "scripts" / "ppc_lab_orchestrate.py"
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(EVIDENCE), *args], text=True, capture_output=True, check=False)


with tempfile.TemporaryDirectory(prefix="ppclab-evidence-test-") as td_text:
    td = Path(td_text)
    store = td / "store"
    init = run("init", str(store))
    assert init.returncode == 0, (init.stdout, init.stderr)

    input_digest = hashlib.sha256(b"target-bytes").hexdigest()
    result = {
        "schema": "ppc-lab-result-v1",
        "backend": "builtin-ppc32be",
        "stop_reason": "return",
        "instructions": 2,
        "pc": "0x10000004",
        "instruction": "0x4e800020",
        "registers": {"r3": "0x0000002a"},
        "lr": "0x00000000", "ctr": "0x00000000", "cr": "0x00000000", "dumps": [],
    }
    response = {
        "schema": "ppc-lab-worker-response-v1", "id": "probe-42", "ok": True,
        "exit_code": 0, "timed_out": False, "engine_version": "1.4.0", "result": result,
    }
    record = {
        "schema": "ppc-lab-fleet-job-result-v1", "name": "constructor-probe",
        "source": "inline", "cache_key": "a" * 64, "engine_version": "1.4.0", "host": "worker-a",
        "attempts": [{"host": "worker-a", "ok": True}],
        "inputs": {"image.path": {"logical_path": "target.bin", "size": 12, "sha256": input_digest}},
        "response": response,
    }
    evidence_dir = td / "evidence"
    evidence_dir.mkdir()
    first = evidence_dir / "first.json"
    second = evidence_dir / "second.json"
    first.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Same semantic JSON, deliberately different byte formatting: should deduplicate.
    second.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    (evidence_dir / "notes.json").write_text(json.dumps({"hello": "not ppclab"}), encoding="utf-8")

    ing = run("ingest", str(store), str(evidence_dir), "--json")
    assert ing.returncode == 0, (ing.stdout, ing.stderr)
    ingested = json.loads(ing.stdout)
    assert ingested["added"] == 1 and ingested["deduplicated"] == 1 and ingested["skipped"] == 1

    q = run("query", str(store), "--engine-version", "1.4.0", "--backend", "builtin-ppc32be",
            "--host", "worker-a", "--ok", "yes", "--input-sha256", input_digest[:16], "--json")
    assert q.returncode == 0, (q.stdout, q.stderr)
    query = json.loads(q.stdout)
    assert query["schema"] == "ppc-lab-evidence-query-v1" and query["count"] == 1
    row = query["results"][0]
    assert row["name"] == "constructor-probe" and row["stop_reason"] == "return"
    assert row["instructions"] == 2 and row["host"] == "worker-a"

    meta = run("show", str(store), str(row["id"]), "--metadata")
    assert meta.returncode == 0, (meta.stdout, meta.stderr)
    metadata = json.loads(meta.stdout)
    assert len(metadata["sources"]) == 2 and metadata["inputs"][0]["sha256"] == input_digest

    shown = run("show", str(store), row["sha256"][:12])
    assert shown.returncode == 0 and json.loads(shown.stdout) == record

    rep = run("report", str(store), "--json")
    assert rep.returncode == 0, (rep.stdout, rep.stderr)
    report = json.loads(rep.stdout)
    assert report["schema"] == "ppc-lab-evidence-report-v1"
    assert report["artifacts"] == 1 and report["sources"] == 2 and report["unique_input_hashes"] == 1
    assert report["success"]["true"] == 1 and report["hosts"]["worker-a"] == 1

    verified = run("verify", str(store), "--json")
    assert verified.returncode == 0, (verified.stdout, verified.stderr)
    assert json.loads(verified.stdout)["ok"] is True

    # Integration: orchestration can publish completed result directories directly.
    code = td / "leaf.bin"
    code.write_bytes(struct.pack(">II", 0x3860002A, 0x4E800020))
    job = {
        "schema": "ppc-lab-job-v1", "id": "orchestrated",
        "image": {"path": "leaf.bin", "kind": "raw", "code_base": "0x10000000"},
        "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100},
    }
    manifest = td / "manifest.json"
    manifest.write_text(json.dumps({"schema": "ppc-lab-orchestration-v1", "jobs": [{"name": "orch-probe", "job": job}]}), encoding="utf-8")
    out = td / "orch-out"
    orch = subprocess.run([
        sys.executable, str(ORCH), str(manifest), "--ppc-lab", str(CLI), "--worker", str(WORKER),
        "--out", str(out), "--root", str(td), "--parallel", "1", "--evidence-store", str(store),
    ], text=True, capture_output=True, check=False)
    assert orch.returncode == 0, (orch.stdout, orch.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["evidence_store"] == str(store.resolve())
    orch_q = run("query", str(store), "--name", "orch-probe", "--json")
    assert orch_q.returncode == 0, (orch_q.stdout, orch_q.stderr)
    assert json.loads(orch_q.stdout)["count"] == 1

    # Corruption is detected by full object hash verification.
    q2 = json.loads(run("query", str(store), "--name", "constructor-probe", "--json").stdout)
    victim = q2["results"][0]["sha256"]
    obj = store / "objects" / "sha256" / victim[:2] / f"{victim}.json"
    original = obj.read_bytes()
    obj.write_bytes(original + b" ")
    broken = run("verify", str(store), "--json")
    assert broken.returncode == 1
    broken_doc = json.loads(broken.stdout)
    assert victim in broken_doc["corrupt"]

print("PASS: PPC Lab content-addressed evidence store/index/orchestration publishing")
