#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "scripts" / "ppc_lab_schedule.py"

with tempfile.TemporaryDirectory(prefix="ppclab-scheduler-test-") as td_text:
    td = Path(td_text)
    fake = td / "fake_campaign.py"
    fake.write_text(r'''#!/usr/bin/env python3
import argparse, json, time
from pathlib import Path
ap=argparse.ArgumentParser(); ap.add_argument("manifest", type=Path); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--resume", action="store_true"); ns=ap.parse_args()
d=json.loads(ns.manifest.read_text()); ns.out.mkdir(parents=True, exist_ok=True)
log=Path(d["log"]); 
with log.open("a", encoding="utf-8") as f: f.write("start:"+d["id"]+"\n")
time.sleep(float(d.get("sleep", 0.02)))
(ns.out/"summary.json").write_text(json.dumps({"schema":"ppc-lab-campaign-summary-v1","status":"complete","id":d["id"]})+"\n")
(ns.out/"state.json").write_text(json.dumps({"schema":"ppc-lab-campaign-state-v1","completed":[]})+"\n")
with log.open("a", encoding="utf-8") as f: f.write("finish:"+d["id"]+"\n")
''', encoding="utf-8")
    log = td / "order.log"
    for cid in ["a-high", "a-low", "b-mid", "c-one", "c-two"]:
        (td / f"{cid}.json").write_text(json.dumps({"id": cid, "log": str(log)}), encoding="utf-8")
    manifest = {
        "schema": "ppc-lab-scheduler-v1",
        "resources": {"max_concurrent": 1},
        "projects": [
            {"id": "a", "weight": 2, "max_concurrent": 1, "case_budget": 10},
            {"id": "b", "weight": 1, "max_concurrent": 1},
            {"id": "c", "weight": 1, "max_concurrent": 1, "case_budget": 5},
        ],
        "campaigns": [
            {"id": "a-low", "project": "a", "manifest": "a-low.json", "priority": 1, "reserve_cases": 2},
            {"id": "a-high", "project": "a", "manifest": "a-high.json", "priority": 50, "reserve_cases": 2},
            {"id": "b-mid", "project": "b", "manifest": "b-mid.json", "priority": 5, "reserve_cases": 1},
            {"id": "c-one", "project": "c", "manifest": "c-one.json", "priority": 9, "reserve_cases": 4},
            {"id": "c-two", "project": "c", "manifest": "c-two.json", "priority": 8, "reserve_cases": 4},
        ],
    }
    mp = td / "scheduler.json"; mp.write_text(json.dumps(manifest), encoding="utf-8")
    out = td / "run"
    p = subprocess.run([sys.executable, str(SCHED), str(mp), "--out", str(out), "--campaign-tool", str(fake)], text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, (p.stdout, p.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == "ppc-lab-scheduler-summary-v1"
    assert summary["counts"]["complete"] == 4
    assert summary["counts"]["quota-blocked"] == 1
    state = json.loads((out / "state.json").read_text())
    assert state["campaigns"]["c-two"]["status"] == "quota-blocked"
    assert state["campaigns"]["c-two"]["reason"] == "project-case-budget"
    starts = [x.split(":",1)[1] for x in log.read_text().splitlines() if x.startswith("start:")]
    assert starts.index("a-high") < starts.index("a-low"), starts
    assert starts.index("b-mid") < starts.index("a-low"), starts  # weighted fair share prevents project A from monopolizing
    blocked_events_before = sum(1 for e in state["events"] if e["kind"] == "quota-blocked" and e["campaign"] == "c-two")

    # Exact resume: terminal quota decisions stay terminal and no duplicate admission/event occurs.
    r = subprocess.run([sys.executable, str(SCHED), str(mp), "--out", str(out), "--campaign-tool", str(fake), "--resume"], text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)
    state2 = json.loads((out / "state.json").read_text())
    blocked_events_after = sum(1 for e in state2["events"] if e["kind"] == "quota-blocked" and e["campaign"] == "c-two")
    assert blocked_events_after == blocked_events_before == 1
    assert [x for x in log.read_text().splitlines() if x.startswith("start:")].__len__() == 4

    # A pre-start cancel marker is terminal and persists across resume.
    manifest2 = {
        "schema": "ppc-lab-scheduler-v1",
        "resources": {"max_concurrent": 1},
        "projects": [{"id": "x"}],
        "campaigns": [{"id": "cancel-me", "project": "x", "manifest": "a-high.json"}],
    }
    mp2 = td / "scheduler-cancel.json"; mp2.write_text(json.dumps(manifest2), encoding="utf-8")
    out2 = td / "cancel-run"; (out2 / "cancel").mkdir(parents=True); (out2 / "cancel" / "cancel-me").write_text("cancel\n")
    c = subprocess.run([sys.executable, str(SCHED), str(mp2), "--out", str(out2), "--campaign-tool", str(fake)], text=True, capture_output=True, timeout=30)
    assert c.returncode == 1
    s2 = json.loads((out2 / "state.json").read_text())
    assert s2["campaigns"]["cancel-me"]["status"] == "cancelled"

print("PASS: weighted fair scheduling, project quota admission, terminal resume semantics, and cancellation markers")
