#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv[1]).resolve()
ORCH = ROOT / "scripts" / "ppc_lab_orchestrate.py"
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"


def invoke(manifest: Path, out: Path, cache: Path, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, str(ORCH), str(manifest), "--ppc-lab", str(CLI), "--worker", str(WORKER),
        "--out", str(out), "--cache", str(cache), "--root", str(root), "--parallel", "2", *extra,
    ], text=True, capture_output=True, check=False)


with tempfile.TemporaryDirectory(prefix="ppclab-orchestrate-test-") as td_text:
    td = Path(td_text)
    code = td / "leaf.bin"
    code.write_bytes(struct.pack(">II", 0x3860002A, 0x4E800020))  # li r3,42 ; blr
    nested = td / "jobs"
    nested.mkdir()
    shutil.copy2(code, nested / "leaf.bin")

    base_job = {
        "schema": "ppc-lab-job-v1",
        "id": "inline",
        "image": {"path": "leaf.bin", "kind": "raw", "code_base": "0x10000000"},
        "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100},
    }
    file_job = dict(base_job)
    file_job["id"] = "file"
    (nested / "file-job.json").write_text(json.dumps(file_job), encoding="utf-8")

    manifest = td / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "ppc-lab-orchestration-v1",
        "id": "smoke",
        "parallelism": 2,
        "jobs": [
            {"name": "inline-case", "job": base_job},
            {"name": "file-case", "path": "jobs/file-job.json"},
        ],
    }), encoding="utf-8")

    out = td / "out"
    cache = td / "cache"
    first = invoke(manifest, out, cache, td)
    assert first.returncode == 0, (first.stdout, first.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == "ppc-lab-orchestration-summary-v1"
    assert summary["jobs"] == 2 and summary["executed"] == 2 and summary["failed"] == 0
    assert summary["parallelism"] == 2
    for row in summary["results"]:
        record = json.loads((out / row["file"]).read_text())
        assert record["schema"] == "ppc-lab-orchestration-job-result-v1"
        assert record["response"]["result"]["registers"]["r3"] == "0x0000002a"
        assert len(record["cache_key"]) == 64

    resumed = invoke(manifest, out, cache, td, "--resume")
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    resumed_summary = json.loads((out / "summary.json").read_text())
    assert resumed_summary["resumed"] == 2 and resumed_summary["executed"] == 0

    shutil.rmtree(out)
    cached = invoke(manifest, out, cache, td)
    assert cached.returncode == 0, (cached.stdout, cached.stderr)
    cached_summary = json.loads((out / "summary.json").read_text())
    assert cached_summary["cache_hits"] == 2 and cached_summary["executed"] == 0

    # Content hashes, not mtimes, invalidate the cache.
    code.write_bytes(struct.pack(">II", 0x3860002B, 0x4E800020))  # li r3,43 ; blr
    (nested / "leaf.bin").write_bytes(code.read_bytes())
    shutil.rmtree(out)
    changed = invoke(manifest, out, cache, td)
    assert changed.returncode == 0, (changed.stdout, changed.stderr)
    changed_summary = json.loads((out / "summary.json").read_text())
    assert changed_summary["executed"] == 2 and changed_summary["cache_hits"] == 0
    for row in changed_summary["results"]:
        record = json.loads((out / row["file"]).read_text())
        assert record["response"]["result"]["registers"]["r3"] == "0x0000002b"

    # Root containment is checked before hashing an input outside the allowed tree.
    outside = td.parent / (td.name + "-outside.bin")
    outside.write_bytes(b"outside")
    try:
        escape_manifest = td / "escape.json"
        escaped_job = dict(base_job)
        escaped_job["image"] = {"path": str(outside), "kind": "raw"}
        escape_manifest.write_text(json.dumps({"schema": "ppc-lab-orchestration-v1", "jobs": [{"job": escaped_job}]}), encoding="utf-8")
        escaped = invoke(escape_manifest, td / "escape-out", cache, td)
        assert escaped.returncode == 2
        assert "outside orchestration root" in escaped.stderr
    finally:
        outside.unlink(missing_ok=True)

print("PASS: PPC Lab parallel/resume/cache orchestration")
