#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv[1]).resolve()
API = ROOT / "scripts" / "ppc_lab_api.py"
EVIDENCE = ROOT / "scripts" / "ppc_lab_evidence.py"


def request(url: str, *, token: str | None = None, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


with tempfile.TemporaryDirectory(prefix="ppclab-api-test-") as td_text:
    td = Path(td_text)
    code = td / "leaf.bin"
    code.write_bytes(struct.pack(">II", 0x3860002A, 0x4E800020))

    store = td / "store"
    init = subprocess.run([sys.executable, str(EVIDENCE), "init", str(store)], text=True, capture_output=True)
    assert init.returncode == 0, (init.stdout, init.stderr)
    digest = hashlib.sha256(code.read_bytes()).hexdigest()
    record = {
        "schema": "ppc-lab-fleet-job-result-v1", "name": "api-evidence", "source": "test",
        "cache_key": "b" * 64, "engine_version": "1.5.0", "host": "api-host",
        "inputs": {"image.path": {"logical_path": "leaf.bin", "size": 8, "sha256": digest}},
        "response": {"schema": "ppc-lab-worker-response-v1", "id": "evidence", "ok": True,
                     "exit_code": 0, "timed_out": False, "engine_version": "1.5.0",
                     "result": {"schema": "ppc-lab-result-v1", "backend": "builtin-ppc32be",
                                "stop_reason": "return", "instructions": 2, "pc": "0x10000004",
                                "registers": {"r3": "0x0000002a"}, "dumps": []}},
    }
    evidence_file = td / "evidence.json"
    evidence_file.write_text(json.dumps(record), encoding="utf-8")
    ing = subprocess.run([sys.executable, str(EVIDENCE), "ingest", str(store), str(evidence_file), "--json"], text=True, capture_output=True)
    assert ing.returncode == 0, (ing.stdout, ing.stderr)

    ready = td / "ready.json"
    token = "unit-test-secret"
    proc = subprocess.Popen([
        sys.executable, str(API), "--ppc-lab", str(CLI), "--root", str(td),
        "--evidence-store", str(store), "--host", "127.0.0.1", "--port", "0",
        "--token", token, "--write-ready", str(ready), "--job-timeout", "10",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not ready.is_file():
            if proc.poll() is not None:
                raise AssertionError(f"API exited early: {proc.stderr.read()}")
            time.sleep(0.05)
        assert ready.is_file(), "API did not become ready"
        info = json.loads(ready.read_text())
        assert info["schema"] == "ppc-lab-api-ready-v1" and info["protocol"] == "ppc-lab-http-api-v1"
        base = info["url"]

        status, unauthorized = request(base + "/v1/health")
        assert status == 401 and unauthorized["error"] == "unauthorized"

        status, health = request(base + "/v1/health", token=token)
        assert status == 200 and health["ok"] is True and health["version"] == "2.0.0"

        status, caps = request(base + "/v1/capabilities", token=token)
        assert status == 200 and caps["protocols"]["http_api"] == "ppc-lab-http-api-v1"
        assert caps["api"]["evidence"] is True

        job = {
            "schema": "ppc-lab-job-v1", "id": "api-run",
            "image": {"path": "leaf.bin", "kind": "raw", "code_base": "0x10000000"},
            "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100},
        }
        status, response = request(base + "/v1/run", token=token, body=job)
        assert status == 200 and response["ok"] is True
        assert response["result"]["registers"]["r3"] == "0x0000002a"

        status, query = request(base + "/v1/evidence/query", token=token, body={"name": "api-evidence", "limit": 5})
        assert status == 200 and query["schema"] == "ppc-lab-evidence-query-v1" and query["count"] == 1
        row = query["results"][0]

        status, shown = request(base + f"/v1/evidence/artifacts/{row['id']}", token=token)
        assert status == 200 and shown["name"] == "api-evidence"

        status, report = request(base + "/v1/evidence/report", token=token)
        assert status == 200 and report["schema"] == "ppc-lab-evidence-report-v1" and report["artifacts"] == 1

        # Oversized and malformed transport requests fail before reaching the worker.
        bad_req = urllib.request.Request(base + "/v1/run", data=b"{", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
        try:
            urllib.request.urlopen(bad_req, timeout=10)
            raise AssertionError("malformed JSON unexpectedly accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=5)

# Remote bind security is enforced before listen. Use a documentation-range address
# so the check does not depend on local interface configuration.
guard = subprocess.run([
    sys.executable, str(API), "--ppc-lab", str(CLI), "--host", "192.0.2.1", "--port", "0"
], text=True, capture_output=True)
assert guard.returncode != 0 and "requires --token" in guard.stderr

print("PASS: PPC Lab authenticated HTTP API, execution, evidence queries, and bind guard")
