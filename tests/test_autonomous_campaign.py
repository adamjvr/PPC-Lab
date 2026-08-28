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
CAMPAIGN = ROOT / "scripts" / "ppc_lab_campaign.py"
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"
EXPLORE = ROOT / "scripts" / "ppc_lab_explore.py"
CORPUS = ROOT / "scripts" / "ppc_lab_corpus.py"
TRIAGE = ROOT / "scripts" / "ppc_lab_triage.py"
EVIDENCE = ROOT / "scripts" / "ppc_lab_evidence.py"


def invoke(manifest: Path, out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        sys.executable, str(CAMPAIGN), str(manifest), "--out", str(out),
        "--ppc-lab", str(CLI), "--worker", str(WORKER),
        "--explorer", str(EXPLORE), "--corpus-tool", str(CORPUS),
        "--triage-tool", str(TRIAGE), "--evidence-tool", str(EVIDENCE),
        *extra,
    ], text=True, capture_output=True, check=False, timeout=120)


with tempfile.TemporaryDirectory(prefix="ppclab-campaign-test-") as td_text:
    td = Path(td_text)
    # cmpwi r3,0 ; beq zero ; li r4,1 ; blr ; zero: li r4,2 ; blr
    code = td / "branch.bin"
    code.write_bytes(struct.pack(">IIIIII", 0x2C030000, 0x4182000C, 0x38800001, 0x4E800020, 0x38800002, 0x4E800020))
    manifest = {
        "schema": "ppc-lab-campaign-v1",
        "name": "branch-autonomy",
        "budgets": {"max_cases": 4, "max_triage_cases": 2, "case_timeout_seconds": 10},
        "exploration": {
            "schema": "ppc-lab-exploration-v1",
            "strategy": "guided",
            "max_cases": 8,
            "base_job": {
                "schema": "ppc-lab-job-v1",
                "id": "campaign-branch",
                "image": {"path": "branch.bin", "kind": "raw", "code_base": "0x10000000"},
                "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 50},
                "registers": {"r3": 0, "r5": 0},
            },
            "axes": [
                {"path": "registers.r3", "values": [0, 1]},
                {"path": "registers.r5", "values": [0, 7]},
            ],
        },
        "corpus": {"path": "campaign-corpus", "promote_novel": True, "verify": True, "replay": True},
        "triage": {"enabled": True, "select": "novel", "left_backend": "builtin", "right_backend": "builtin"},
        "evidence": {"publish": True, "store": "campaign-evidence", "verify": True},
    }
    mp = td / "campaign.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    out = td / "campaign-run"

    p = invoke(mp, out)
    assert p.returncode == 0, (p.stdout, p.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == "ppc-lab-campaign-summary-v1"
    assert summary["status"] in ("complete", "complete-with-findings")
    assert summary["exploration"]["evaluated_cases"] >= 3
    assert summary["exploration"]["novel_cases"] >= 2
    assert summary["corpus"]["promoted_cases"] >= 1
    assert summary["corpus"]["replay"]["failed"] == 0
    assert summary["triage"]["selected"] >= 1
    assert summary["triage"]["divergences"] == 0
    assert summary["evidence"]["published"] is True
    assert summary["evidence"]["verify"]["ok"] is True
    assert (td / "campaign-corpus" / "manifest.json").is_file()
    assert (td / "campaign-evidence" / "evidence.sqlite3").is_file()
    assert list((out / "triage").glob("*/bundle/manifest.json"))

    # Resume must reuse completed stage checkpoints rather than duplicate the work.
    state_before = json.loads((out / "state.json").read_text())
    r = invoke(mp, out, "--resume")
    assert r.returncode == 0, (r.stdout, r.stderr)
    state_after = json.loads((out / "state.json").read_text())
    assert state_after["completed"] == state_before["completed"] == ["exploration", "corpus", "triage", "evidence"]

    # Dry-run validates and resolves the campaign without executing target code.
    dry = td / "dry-run"
    d = invoke(mp, dry, "--dry-run")
    assert d.returncode == 0, (d.stdout, d.stderr)
    dry_summary = json.loads((dry / "summary.json").read_text())
    assert dry_summary["status"] == "dry-run"
    assert not (dry / "exploration").exists()

    # Target-input root escapes are rejected before exploration/hash/execution.
    outside = td.parent / (td.name + "-outside.bin")
    outside.write_bytes(b"outside")
    try:
        escaped = json.loads(json.dumps(manifest))
        escaped["exploration"]["base_job"]["image"]["path"] = str(outside)
        ep = td / "escape.json"
        ep.write_text(json.dumps(escaped), encoding="utf-8")
        e = invoke(ep, td / "escape-out")
        assert e.returncode == 2 and "outside campaign root" in e.stderr
    finally:
        outside.unlink(missing_ok=True)

print("PASS: autonomous exploration, corpus replay, triage, evidence publication, resume, dry-run, and root safety")
