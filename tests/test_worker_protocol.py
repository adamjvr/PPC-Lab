#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv[1]).resolve()
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"


def invoke(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(WORKER), "--ppc-lab", str(CLI), *args],
                          input=stdin, text=True, capture_output=True, check=False)


with tempfile.TemporaryDirectory(prefix="ppclab-worker-test-") as td_text:
    td = Path(td_text)
    code = td / "leaf.bin"
    code.write_bytes(struct.pack(">II", 0x3860002A, 0x4E800020))  # li r3,42 ; blr
    job = {
        "schema": "ppc-lab-job-v1",
        "id": "single",
        "image": {"path": "leaf.bin", "kind": "raw", "code_base": "0x10000000"},
        "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100},
    }
    job_path = td / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    one = invoke(["--root", str(td), "run", str(job_path)])
    assert one.returncode == 0, (one.stdout, one.stderr)
    response = json.loads(one.stdout)
    assert response["schema"] == "ppc-lab-worker-response-v1"
    assert response["id"] == "single" and response["ok"] is True
    assert response["result"]["registers"]["r3"] == "0x0000002a"
    assert response["snapshot"]["cpu"]["gpr"][3] == "0x0000002a"

    # A guest stop is a valid response but failed execution status.
    bad_job = dict(job)
    bad_job["id"] = "limit"
    bad_job["execution"] = dict(job["execution"], max_instructions=1)
    limited_path = td / "limit.json"
    limited_path.write_text(json.dumps(bad_job), encoding="utf-8")
    limited = invoke(["--root", str(td), "run", str(limited_path)])
    assert limited.returncode == 1
    limited_response = json.loads(limited.stdout)
    assert limited_response["ok"] is False and limited_response["exit_code"] == 5
    assert limited_response["result"]["stop_reason"] == "instruction_limit"

    # Root containment follows symlinks/real paths and rejects escape attempts.
    escape = dict(job)
    escape["id"] = "escape"
    escape["image"] = {"path": "/etc/passwd", "kind": "raw"}
    escape_path = td / "escape.json"
    escape_path.write_text(json.dumps(escape), encoding="utf-8")
    escaped = invoke(["--root", str(td), "run", str(escape_path)])
    assert escaped.returncode == 1
    escaped_response = json.loads(escaped.stdout)
    assert escaped_response["ok"] is False and "outside worker root" in escaped_response["error"]

    # Stream mode survives an ordinary failed job and keeps response ordering.
    stream_job = dict(job)
    stream_job["image"] = dict(job["image"], path=str(code))
    stream_bad = dict(stream_job)
    stream_bad["id"] = "bad-schema"
    stream_bad["schema"] = "wrong"
    payload = json.dumps(stream_job) + "\n" + json.dumps(stream_bad) + "\n"
    streamed = invoke(["--root", str(td), "stream"], stdin=payload)
    assert streamed.returncode == 0, (streamed.stdout, streamed.stderr)
    rows = [json.loads(line) for line in streamed.stdout.splitlines() if line.strip()]
    assert len(rows) == 2 and rows[0]["ok"] is True and rows[1]["ok"] is False

    # Malformed transport JSON gets a response and a distinct stream status.
    malformed = invoke(["--root", str(td), "stream"], stdin="{not-json}\n")
    assert malformed.returncode == 2
    malformed_response = json.loads(malformed.stdout)
    assert malformed_response["ok"] is False and "invalid JSON" in malformed_response["error"]

print("PASS: PPC Lab worker JSON/NDJSON protocol")
