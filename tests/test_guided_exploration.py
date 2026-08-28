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
EXPLORE = ROOT / "scripts" / "ppc_lab_explore.py"
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"
CORPUS = ROOT / "scripts" / "ppc_lab_corpus.py"


def run(manifest: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, str(EXPLORE), str(manifest), "--out", str(out),
        "--ppc-lab", str(CLI), "--worker", str(WORKER), "--corpus-tool", str(CORPUS),
        *extra,
    ], text=True, capture_output=True, check=False)


with tempfile.TemporaryDirectory(prefix="ppclab-explore-test-") as td_text:
    td = Path(td_text)
    # cmpwi r3,0 ; beq zero ; li r4,1 ; blr ; zero: li r4,2 ; blr
    code = td / "branch.bin"
    code.write_bytes(struct.pack(">IIIIII", 0x2C030000, 0x4182000C, 0x38800001, 0x4E800020, 0x38800002, 0x4E800020))
    manifest = {
        "schema": "ppc-lab-exploration-v1",
        "strategy": "guided",
        "max_cases": 8,
        "base_job": {
            "schema": "ppc-lab-job-v1",
            "id": "explore-branch",
            "image": {"path": "branch.bin", "kind": "raw", "code_base": "0x10000000"},
            "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 50},
            "registers": {"r3": 0, "r5": 0}
        },
        "axes": [
            {"path": "registers.r3", "values": [0, 1]},
            {"path": "registers.r5", "values": [0, 7]}
        ]
    }
    mp = td / "explore.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    out = td / "out"
    p = run(mp, out)
    assert p.returncode == 0, (p.stdout, p.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == "ppc-lab-exploration-summary-v1"
    assert summary["evaluated_cases"] >= 3
    assert summary["novel_cases"] >= 2
    assert summary["unique_pcs"] >= 5
    assert summary["input_provenance"][0]["sha256"]
    rows = [json.loads(x.read_text()) for x in sorted((out / "cases").glob("*.json"))]
    assert any(r["novelty"]["new_pc_count"] > 0 for r in rows)
    assert any(r["novelty"]["behavior_novel"] for r in rows)

    # Adaptive mode prioritizes high-yield axes and can conserve its case budget on a novelty plateau.
    adaptive = json.loads(json.dumps(manifest))
    adaptive["strategy"] = "adaptive"
    adaptive["max_cases"] = 12
    adaptive["adaptive"] = {"plateau_window": 1, "plateau_novelty_rate": 0.0, "min_cases": 3}
    apath = td / "adaptive.json"
    apath.write_text(json.dumps(adaptive), encoding="utf-8")
    aout = td / "adaptive-out"
    arun = run(apath, aout)
    assert arun.returncode == 0, (arun.stdout, arun.stderr)
    asum = json.loads((aout / "summary.json").read_text())
    assert asum["strategy"] == "adaptive"
    assert "registers.r3" in asum["axis_yield"] and "registers.r5" in asum["axis_yield"]
    assert asum["adaptive"]["stopped_early"] is True
    assert asum["adaptive"]["unused_case_budget"] > 0

    # Direct promotion preserves private-input behavior: cases reference the target by hash.
    corpus = td / "corpus"
    out2 = td / "out-promote"
    p2 = run(mp, out2, "--promote-corpus", str(corpus))
    assert p2.returncode == 0, (p2.stdout, p2.stderr)
    summary2 = json.loads((out2 / "summary.json").read_text())
    assert summary2["promoted_cases"] >= 1
    promoted = [json.loads(x.read_text()) for x in (corpus / "cases").glob("*.json")]
    assert promoted and all(not spec.get("embedded") for case in promoted for spec in case["inputs"])

    # Structural fields cannot be explored.
    bad = dict(manifest)
    bad["axes"] = [{"path": "image.path", "values": ["branch.bin", "other.bin"]}]
    bp = td / "bad.json"
    bp.write_text(json.dumps(bad), encoding="utf-8")
    b = run(bp, td / "bad-out")
    assert b.returncode == 2 and "cannot mutate structural field" in b.stderr

    # Root escape is rejected before target hashing/execution.
    outside = td.parent / (td.name + "-outside.bin")
    outside.write_bytes(b"outside")
    try:
        escaped = dict(manifest)
        escaped["base_job"] = json.loads(json.dumps(manifest["base_job"]))
        escaped["base_job"]["image"]["path"] = str(outside)
        ep = td / "escape.json"
        ep.write_text(json.dumps(escaped), encoding="utf-8")
        e = run(ep, td / "escape-out")
        assert e.returncode == 2 and "outside exploration root" in e.stderr
    finally:
        outside.unlink(missing_ok=True)

print("PASS: deterministic guided exploration, novelty, corpus promotion, and root safety")
