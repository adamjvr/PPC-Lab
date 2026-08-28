#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIORITIZE = ROOT / "scripts" / "ppc_lab_prioritize.py"


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


with tempfile.TemporaryDirectory(prefix="ppclab-priority-test-") as td_text:
    td = Path(td_text)
    exp = td / "exploration"
    cases = exp / "cases"
    cases.mkdir(parents=True)
    dump(exp / "summary.json", {
        "schema": "ppc-lab-exploration-summary-v1", "strategy": "adaptive", "evaluated_cases": 4,
    })
    rows = [
        {"index": 0, "parent": None, "assignment": {"registers.r3": 0}, "novel": True,
         "novelty": {"new_pc_count": 1, "behavior_novel": True}, "behavior_sha256": "a"*64,
         "trace": {"pcs": ["0x10000000", "0x10000004"]}, "worker": {"ok": True}},
        {"index": 1, "parent": 0, "assignment": {"registers.r3": 1}, "novel": False,
         "novelty": {"new_pc_count": 0, "behavior_novel": False}, "behavior_sha256": "a"*64,
         "trace": {"pcs": ["0x10000000"]}, "worker": {"ok": False}},
        {"index": 2, "parent": 0, "assignment": {"registers.r3": 2}, "novel": True,
         "novelty": {"new_pc_count": 3, "behavior_novel": True}, "behavior_sha256": "b"*64,
         "trace": {"pcs": ["0x10000000", "0x10000008", "0x1000000c", "0x10000010"]}, "worker": {"ok": True}},
        {"index": 3, "parent": 2, "assignment": {"registers.r3": 3}, "novel": False,
         "novelty": {"new_pc_count": 0, "behavior_novel": False}, "behavior_sha256": "b"*64,
         "trace": {"pcs": ["0x10000000"]}, "worker": {"ok": True}},
    ]
    for row in rows:
        row = {"schema": "ppc-lab-exploration-case-v1", **row}
        dump(cases / f"{row['index']:05d}.json", row)

    report = td / "priority.json"
    p = subprocess.run([sys.executable, str(PRIORITIZE), str(exp), "--json", str(report), "--top", "3",
                        "--plateau-window", "1", "--plateau-novelty-rate", "0"],
                       text=True, capture_output=True, check=False)
    assert p.returncode == 0, (p.stdout, p.stderr)
    doc = json.loads(report.read_text())
    assert doc["schema"] == "ppc-lab-priority-report-v1"
    assert doc["ranking"][0]["index"] in (1, 2)
    assert doc["ranking"][0]["score"] > doc["ranking"][-1]["score"]
    assert doc["recommended_cases"] == [row["index"] for row in doc["ranking"][:3]]
    assert doc["axes"][0]["path"] == "registers.r3"
    assert doc["plateau"]["saturated"] is True

print("PASS: deterministic case prioritization, axis yield analysis, and plateau detection")
