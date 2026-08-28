#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROL_PATH = ROOT / "scripts" / "ppc_lab_control.py"
spec = importlib.util.spec_from_file_location("ppc_lab_control", CONTROL_PATH)
assert spec and spec.loader
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def wait_for(predicate, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError("timed out waiting for condition")


def write_manifest(path: pathlib.Path, delay: float) -> None:
    path.write_text(json.dumps({"schema": "ppc-lab-scheduler-v1", "fake_delay": delay}) + "\n", encoding="utf-8")


def ns(**kwargs):
    return SimpleNamespace(**kwargs)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ppclab-control-") as td:
        base = pathlib.Path(td)
        control_root = base / "control"
        starts = base / "starts.ndjson"
        fake = base / "fake_schedule.py"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse,json,os,pathlib,sys,time\n"
            "ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=pathlib.Path); ap.add_argument('--out',type=pathlib.Path,required=True); ap.add_argument('--resume',action='store_true'); ns=ap.parse_args()\n"
            f"starts=pathlib.Path({str(starts)!r})\n"
            "doc=json.loads(ns.manifest.read_text()); ns.out.mkdir(parents=True,exist_ok=True)\n"
            "with starts.open('a') as f: f.write(json.dumps({'name':ns.manifest.stem,'resume':ns.resume})+'\\n')\n"
            "state={'schema':'ppc-lab-scheduler-state-v1','projects':{'p':{}},'campaigns':{'c':{'id':'c','status':'running','pid':os.getpid()}},'events':[{'kind':'started'}]}\n"
            "(ns.out/'state.json').write_text(json.dumps(state))\n"
            "end=time.time()+float(doc.get('fake_delay',0.1))\n"
            "while time.time()<end:\n"
            "  if (ns.out/'CANCEL').exists():\n"
            "    summary={'schema':'ppc-lab-scheduler-summary-v1','status':'complete-with-failures','counts':{'cancelled':1},'projects':{},'campaigns':[{'id':'c','status':'cancelled'}],'events':[]}\n"
            "    (ns.out/'summary.json').write_text(json.dumps(summary)); sys.exit(1)\n"
            "  time.sleep(0.02)\n"
            "summary={'schema':'ppc-lab-scheduler-summary-v1','status':'complete','counts':{'complete':1},'projects':{},'campaigns':[{'id':'c','status':'complete'}],'events':[]}\n"
            "(ns.out/'summary.json').write_text(json.dumps(summary)); sys.exit(0)\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)

        high = base / "high.json"; write_manifest(high, 0.65)
        low = base / "low.json"; write_manifest(low, 0.05)
        gone = base / "gone.json"; write_manifest(gone, 0.05)
        slow = base / "slow.json"; write_manifest(slow, 0.8)
        drained = base / "drained.json"; write_manifest(drained, 0.05)
        changed = base / "changed.json"; write_manifest(changed, 0.05)

        assert control.command_init(ns(root=control_root)) == 0
        assert control.command_submit(ns(root=control_root, manifest=low, id="low", priority=1)) == 0
        assert control.command_submit(ns(root=control_root, manifest=high, id="high", priority=50)) == 0
        assert control.command_submit(ns(root=control_root, manifest=gone, id="gone", priority=100)) == 0
        assert control.command_cancel(ns(root=control_root, id="gone", all=False)) == 0
        assert control.command_pause(ns(root=control_root)) == 0

        server = subprocess.Popen([
            sys.executable, str(CONTROL_PATH), "serve", str(control_root),
            "--scheduler-tool", str(fake), "--max-active", "1", "--poll-seconds", "0.02", "--until-idle",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        time.sleep(0.15)
        assert not starts.exists(), "paused control plane dispatched work"
        status = control.make_telemetry(control_root)
        assert status["schema"] == "ppc-lab-control-telemetry-v1"
        assert status["paused"] is True and status["queue_depth"] == 2

        assert control.command_resume(ns(root=control_root)) == 0
        wait_for(lambda: starts.exists() and len(starts.read_text(encoding="utf-8").splitlines()) >= 1)
        first = json.loads(starts.read_text(encoding="utf-8").splitlines()[0])
        assert first["name"] == "high", first
        wait_for(lambda: (control_root / "runs" / "high" / "state.json").is_file())
        live = control.make_telemetry(control_root)
        row = next(row for row in live["active"] if (row.get("scheduler") or {}).get("campaign_counts", {}).get("running") == 1)
        assert row["scheduler"]["campaign_process_pids"]
        assert server.wait(timeout=12) == 0, server.stderr.read() if server.stderr else ""
        order = [json.loads(x)["name"] for x in starts.read_text(encoding="utf-8").splitlines()]
        assert order[:2] == ["high", "low"], order

        hist = control.read_history(control_root)
        by_id = {r["id"]: r for r in hist}
        assert by_id["gone"]["status"] == "cancelled"
        assert by_id["high"]["status"] == "complete" and by_id["low"]["status"] == "complete"

        # Running cancellation propagates through the scheduler's established CANCEL marker.
        assert control.command_submit(ns(root=control_root, manifest=slow, id="slow", priority=5)) == 0
        server = subprocess.Popen([
            sys.executable, str(CONTROL_PATH), "serve", str(control_root), "--scheduler-tool", str(fake),
            "--max-active", "1", "--poll-seconds", "0.02", "--until-idle",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        wait_for(lambda: json.loads((control_root / "queue" / "slow.json").read_text())["status"] == "running")
        assert control.command_cancel(ns(root=control_root, id="slow", all=False)) == 0
        assert server.wait(timeout=12) == 0, server.stderr.read() if server.stderr else ""
        slow_item = json.loads((control_root / "queue" / "slow.json").read_text())
        assert slow_item["status"] == "cancelled", slow_item

        # Drain is graceful and reversible: queued work stays queued until resume.
        assert control.command_submit(ns(root=control_root, manifest=drained, id="drained", priority=5)) == 0
        assert control.command_drain(ns(root=control_root)) == 0
        drained_server = subprocess.run([
            sys.executable, str(CONTROL_PATH), "serve", str(control_root), "--scheduler-tool", str(fake), "--until-idle"
        ], text=True, capture_output=True, timeout=12)
        assert drained_server.returncode == 0, drained_server.stderr
        assert json.loads((control_root / "queue" / "drained.json").read_text())["status"] == "queued"
        assert control.command_resume(ns(root=control_root)) == 0
        final_server = subprocess.run([
            sys.executable, str(CONTROL_PATH), "serve", str(control_root), "--scheduler-tool", str(fake), "--until-idle"
        ], text=True, capture_output=True, timeout=12)
        assert final_server.returncode == 0, final_server.stderr
        assert json.loads((control_root / "queue" / "drained.json").read_text())["status"] == "complete"

        # A queued scheduler manifest is content-pinned; edits after submission are never executed silently.
        assert control.command_submit(ns(root=control_root, manifest=changed, id="changed", priority=99)) == 0
        changed.write_text(json.dumps({"schema": "ppc-lab-scheduler-v1", "fake_delay": 9.0}) + "\n", encoding="utf-8")
        changed_server = subprocess.run([
            sys.executable, str(CONTROL_PATH), "serve", str(control_root), "--scheduler-tool", str(fake), "--until-idle"
        ], text=True, capture_output=True, timeout=12)
        assert changed_server.returncode == 0, changed_server.stderr
        changed_item = json.loads((control_root / "queue" / "changed.json").read_text())
        assert changed_item["status"] == "failed" and changed_item["failure_reason"] == "manifest-sha256-changed"

        telemetry = control.make_telemetry(control_root)
        assert telemetry["queue_depth"] == 0
        assert telemetry["counts"]["complete"] == 3
        assert telemetry["counts"]["cancelled"] == 2
        assert telemetry["counts"]["failed"] == 1
        assert (control_root / "history" / "drained.json").is_file()
        assert all(r["schema"] == "ppc-lab-control-history-record-v1" for r in control.read_history(control_root))

        # CLI status parser/surface gets one direct smoke check without bloating the test with subprocess startup.
        cli = subprocess.run([sys.executable, str(CONTROL_PATH), "status", str(control_root), "--json"], text=True, capture_output=True, timeout=8)
        assert cli.returncode == 0, cli.stderr
        assert json.loads(cli.stdout)["schema"] == "ppc-lab-control-telemetry-v1"

    print("PASS: persistent campaign control plane, live telemetry, controls, history, and priority queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
