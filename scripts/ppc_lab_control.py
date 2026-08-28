#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Persistent PPC Lab campaign control plane.

The control plane is a dependency-free supervisor above ``ppc-lab-schedule``.
It owns a filesystem-backed queue and campaign-run history while leaving all
research semantics inside the existing scheduler/campaign layers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CONTROL_SCHEMA = "ppc-lab-control-v1"
ITEM_SCHEMA = "ppc-lab-control-item-v1"
LOCK_SCHEMA = "ppc-lab-control-lock-internal-v1"
TELEMETRY_SCHEMA = "ppc-lab-control-telemetry-v1"
HISTORY_SCHEMA = "ppc-lab-control-history-v1"
HISTORY_RECORD_SCHEMA = "ppc-lab-control-history-record-v1"
SCHEDULER_SCHEMA = "ppc-lab-scheduler-v1"
TERMINAL = {"complete", "failed", "cancelled", "quota-blocked"}


class ControlError(RuntimeError):
    pass


def now() -> float:
    return time.time()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_id(value: str, label: str = "id") -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not value or any(c not in allowed for c in value):
        raise ControlError(f"{label} must be a non-empty portable identifier")
    return value


def ensure_root(root: Path, *, create: bool = False) -> Path:
    root = root.expanduser().resolve()
    state = root / "control.json"
    if create:
        root.mkdir(parents=True, exist_ok=True)
        for name in ["queue", "runs", "logs", "history"]:
            (root / name).mkdir(exist_ok=True)
        if not state.exists():
            write_json(state, {
                "schema": CONTROL_SCHEMA,
                "created_unix": now(),
                "next_seq": 1,
            })
    if not state.is_file():
        raise ControlError(f"control plane is not initialized: {root}; run init first")
    doc = read_json(state)
    if doc.get("schema") != CONTROL_SCHEMA:
        raise ControlError(f"unsupported control-plane schema in {state}")
    return root


def queue_paths(root: Path) -> list[Path]:
    return sorted((root / "queue").glob("*.json"))


def load_items(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in queue_paths(root):
        try:
            doc = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlError(f"cannot read queue item {path}: {exc}") from exc
        if doc.get("schema") != ITEM_SCHEMA:
            raise ControlError(f"unsupported queue item schema: {path}")
        doc["_path"] = str(path)
        items.append(doc)
    return items


def item_path(root: Path, item_id: str) -> Path:
    return root / "queue" / f"{validate_id(item_id)}.json"


def save_item(root: Path, item: dict[str, Any]) -> None:
    clean = {k: v for k, v in item.items() if not k.startswith("_")}
    write_json(item_path(root, str(item["id"])), clean)


def control_state(root: Path) -> dict[str, Any]:
    return read_json(root / "control.json")


def save_control_state(root: Path, doc: dict[str, Any]) -> None:
    write_json(root / "control.json", doc)


def resolve_scheduler(value: str | None) -> Path:
    candidate = value or shutil.which("ppc-lab-schedule")
    if not candidate:
        raise ControlError("cannot find ppc-lab-schedule; use --scheduler-tool")
    p = Path(candidate).expanduser().resolve()
    if not p.is_file():
        raise ControlError(f"scheduler tool is not a file: {p}")
    return p


def tool_command(tool: Path, *args: str) -> list[str]:
    return [sys.executable, str(tool), *args] if tool.suffix == ".py" else [str(tool), *args]


def proc_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(root: Path) -> Path:
    lock = root / "SERVER.lock"
    if lock.exists():
        try:
            old = read_json(lock)
            pid = int(old.get("pid", 0))
        except Exception:
            pid = 0
        if proc_alive(pid):
            raise ControlError(f"control plane already serving as pid {pid}")
        lock.unlink(missing_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"schema": LOCK_SCHEMA, "pid": os.getpid(), "started_unix": now()}, f, sort_keys=True)
        f.write("\n")
    return lock


def history_path(root: Path) -> Path:
    return root / "history" / "history.ndjson"


def read_history(root: Path) -> list[dict[str, Any]]:
    path = history_path(root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def scheduler_snapshot(item: dict[str, Any]) -> dict[str, Any] | None:
    run_out = Path(str(item["run_out"]))
    state = run_out / "state.json"
    summary = run_out / "summary.json"
    source = summary if summary.is_file() else state if state.is_file() else None
    if source is None:
        return None
    try:
        doc = read_json(source)
    except Exception:
        return {"source": str(source), "read_error": True}
    projects = doc.get("projects") if isinstance(doc.get("projects"), dict) else {}
    campaigns_raw = doc.get("campaigns")
    if isinstance(campaigns_raw, dict):
        campaigns = list(campaigns_raw.values())
    elif isinstance(campaigns_raw, list):
        campaigns = campaigns_raw
    else:
        campaigns = []
    counts: dict[str, int] = {}
    pids: list[int] = []
    for rec in campaigns:
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status == "running" and isinstance(rec.get("pid"), int):
            pids.append(int(rec["pid"]))
    return {
        "source": str(source),
        "scheduler_status": doc.get("status"),
        "campaign_counts": dict(sorted(counts.items())),
        "project_count": len(projects),
        "campaign_process_pids": sorted(pids),
        "event_count": len(doc.get("events", [])) if isinstance(doc.get("events"), list) else 0,
    }


def make_telemetry(root: Path, active: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    items = load_items(root)
    counts: dict[str, int] = {}
    active_rows: list[dict[str, Any]] = []
    for item in items:
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        if status == "running":
            live = active.get(str(item["id"])) if active is not None else None
            pid = int(live["proc"].pid) if live else item.get("pid")
            started = float(item.get("started_unix", now()))
            active_rows.append({
                "id": item["id"],
                "priority": item.get("priority", 0),
                "pid": pid,
                "pid_alive": proc_alive(pid if isinstance(pid, int) else None),
                "uptime_seconds": max(0.0, round(now() - started, 6)),
                "scheduler": scheduler_snapshot(item),
            })
    return {
        "schema": TELEMETRY_SCHEMA,
        "unix": now(),
        "paused": (root / "PAUSE").exists(),
        "draining": (root / "DRAIN").exists(),
        "global_cancel": (root / "CANCEL").exists(),
        "counts": dict(sorted(counts.items())),
        "active": sorted(active_rows, key=lambda r: str(r["id"])),
        "queue_depth": counts.get("queued", 0),
        "history_count": len(read_history(root)),
    }


def write_telemetry(root: Path, active: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    doc = make_telemetry(root, active)
    write_json(root / "telemetry.json", doc)
    return doc


def archive_terminal(root: Path, item: dict[str, Any]) -> None:
    if item.get("history_written"):
        return
    sched_summary = None
    sp = Path(str(item["run_out"])) / "summary.json"
    if sp.is_file():
        try:
            sched_summary = read_json(sp)
        except Exception:
            pass
    rec = {
        "schema": HISTORY_RECORD_SCHEMA,
        "id": item["id"],
        "seq": item["seq"],
        "priority": item.get("priority", 0),
        "manifest": item["manifest"],
        "manifest_sha256": item["manifest_sha256"],
        "status": item["status"],
        "submitted_unix": item["submitted_unix"],
        "started_unix": item.get("started_unix"),
        "finished_unix": item.get("finished_unix"),
        "returncode": item.get("returncode"),
        "attempts": item.get("attempts", 0),
        "run_out": item["run_out"],
        "scheduler_summary": sched_summary,
    }
    append_jsonl(history_path(root), rec)
    write_json(root / "history" / f"{item['id']}.json", rec)
    item["history_written"] = True
    save_item(root, item)


def choose_queued(root: Path) -> dict[str, Any] | None:
    queued = [x for x in load_items(root) if x.get("status") == "queued"]
    if not queued:
        return None
    return min(queued, key=lambda x: (-int(x.get("priority", 0)), int(x.get("seq", 0)), str(x["id"])))


def command_init(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root, create=True)
    write_telemetry(root)
    print(json.dumps({"schema": CONTROL_SCHEMA, "root": str(root), "status": "initialized"}, sort_keys=True))
    return 0


def command_submit(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    manifest = ns.manifest.expanduser().resolve(strict=True)
    doc = read_json(manifest)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEDULER_SCHEMA:
        raise ControlError(f"submitted manifest must use schema {SCHEDULER_SCHEMA}")
    state = control_state(root)
    seq = int(state.get("next_seq", 1))
    item_id = validate_id(ns.id or f"run-{seq:06d}")
    path = item_path(root, item_id)
    if path.exists():
        raise ControlError(f"queue item already exists: {item_id}")
    run_out = (root / "runs" / item_id).resolve()
    item = {
        "schema": ITEM_SCHEMA,
        "id": item_id,
        "seq": seq,
        "priority": int(ns.priority),
        "manifest": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "run_out": str(run_out),
        "status": "queued",
        "submitted_unix": now(),
        "attempts": 0,
    }
    save_item(root, item)
    state["next_seq"] = seq + 1
    save_control_state(root, state)
    write_telemetry(root)
    print(json.dumps({k: v for k, v in item.items() if not k.startswith("_")}, sort_keys=True))
    return 0


def command_status(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    interval = float(ns.watch or 0.0)
    while True:
        doc = write_telemetry(root)
        if ns.json or interval > 0:
            print(json.dumps(doc, sort_keys=True), flush=True)
        else:
            print(f"PPC Lab control plane: {root}")
            print(f"paused={doc['paused']} draining={doc['draining']} queue={doc['queue_depth']} history={doc['history_count']}")
            print("counts=" + json.dumps(doc["counts"], sort_keys=True))
            for row in doc["active"]:
                sched = row.get("scheduler") or {}
                print(f"running {row['id']} pid={row['pid']} uptime={row['uptime_seconds']:.1f}s campaigns={sched.get('campaign_counts', {})}")
        if interval <= 0:
            break
        time.sleep(interval)
    return 0


def command_history(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    rows = read_history(root)
    if ns.limit is not None:
        limit = max(0, int(ns.limit))
        rows = [] if limit == 0 else rows[-limit:]
    if ns.json:
        print(json.dumps({"schema": HISTORY_SCHEMA, "records": rows}, sort_keys=True))
    else:
        for row in rows:
            print(f"{row.get('id')}\t{row.get('status')}\tpriority={row.get('priority')}\trc={row.get('returncode')}")
    return 0


def touch(root: Path, name: str) -> None:
    (root / name).write_text(f"{now():.6f}\n", encoding="utf-8")


def command_pause(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    touch(root, "PAUSE")
    write_telemetry(root)
    print("paused")
    return 0


def command_resume(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    (root / "PAUSE").unlink(missing_ok=True)
    (root / "DRAIN").unlink(missing_ok=True)
    (root / "CANCEL").unlink(missing_ok=True)
    write_telemetry(root)
    print("resumed")
    return 0


def command_drain(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    touch(root, "DRAIN")
    write_telemetry(root)
    print("draining")
    return 0


def command_cancel(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    if ns.all:
        touch(root, "CANCEL")
        for item in load_items(root):
            if item.get("status") == "queued":
                item.update(status="cancelled", finished_unix=now(), cancel_reason="control-global-cancel")
                save_item(root, item)
                archive_terminal(root, item)
            elif item.get("status") == "running":
                run_out = Path(str(item["run_out"]))
                run_out.mkdir(parents=True, exist_ok=True)
                touch(run_out, "CANCEL")
        write_telemetry(root)
        print("cancel-all requested")
        return 0
    if not ns.id:
        raise ControlError("cancel requires ITEM_ID or --all")
    path = item_path(root, ns.id)
    if not path.is_file():
        raise ControlError(f"unknown queue item: {ns.id}")
    item = read_json(path)
    status = item.get("status")
    if status == "queued":
        item.update(status="cancelled", finished_unix=now(), cancel_reason="control-cancel-before-start")
        save_item(root, item)
        archive_terminal(root, item)
    elif status == "running":
        run_out = Path(str(item["run_out"]))
        run_out.mkdir(parents=True, exist_ok=True)
        touch(run_out, "CANCEL")
        item["cancel_requested_unix"] = now()
        save_item(root, item)
    elif status == "orphaned":
        pid = item.get("orphan_pid")
        if isinstance(pid, int) and proc_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        item.update(status="cancelled", finished_unix=now(), cancel_reason="control-orphan-cancel")
        save_item(root, item)
        archive_terminal(root, item)
    print(f"cancel requested: {ns.id}")
    write_telemetry(root)
    return 0


def recover_state(root: Path) -> None:
    for item in load_items(root):
        if item.get("status") != "running":
            continue
        pid = item.get("pid")
        if isinstance(pid, int) and proc_alive(pid):
            item["status"] = "orphaned"
            item["orphaned_unix"] = now()
            item["orphan_pid"] = pid
            save_item(root, item)
            continue
        item["status"] = "queued"
        item.pop("pid", None)
        item["recovered_unix"] = now()
        save_item(root, item)


def serve(root: Path, scheduler: Path, max_active: int, poll: float, until_idle: bool) -> int:
    lock = acquire_lock(root)
    active: dict[str, dict[str, Any]] = {}
    stop = False

    def on_signal(signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True
        touch(root, "DRAIN")
        for item in active.values():
            try:
                item["proc"].terminate()
            except Exception:
                pass

    old_int = signal.signal(signal.SIGINT, on_signal)
    old_term = signal.signal(signal.SIGTERM, on_signal)
    try:
        recover_state(root)
        while True:
            global_cancel = (root / "CANCEL").exists()
            paused = (root / "PAUSE").exists()
            draining = (root / "DRAIN").exists() or stop

            if global_cancel:
                for item in load_items(root):
                    if item.get("status") == "queued":
                        item.update(status="cancelled", finished_unix=now(), cancel_reason="control-global-cancel")
                        save_item(root, item)
                        archive_terminal(root, item)
                    elif item.get("status") == "running":
                        run_out = Path(str(item["run_out"]))
                        run_out.mkdir(parents=True, exist_ok=True)
                        touch(run_out, "CANCEL")
                    elif item.get("status") == "orphaned":
                        pid = item.get("orphan_pid")
                        if isinstance(pid, int) and proc_alive(pid):
                            try:
                                os.kill(pid, signal.SIGTERM)
                            except OSError:
                                pass
                        item.update(status="cancelled", finished_unix=now(), cancel_reason="control-global-orphan-cancel")
                        save_item(root, item)
                        archive_terminal(root, item)

            for item_id, live in list(active.items()):
                proc: subprocess.Popen[Any] = live["proc"]
                rc = proc.poll()
                if rc is None:
                    continue
                item = read_json(item_path(root, item_id))
                sched_summary = Path(str(item["run_out"])) / "summary.json"
                sched_status = None
                if sched_summary.is_file():
                    try:
                        sched_status = read_json(sched_summary).get("status")
                    except Exception:
                        pass
                if item.get("cancel_requested_unix") or global_cancel:
                    status = "cancelled"
                elif rc == 0 and sched_status in {None, "complete", "drained"}:
                    status = "complete"
                else:
                    status = "failed"
                item.update(status=status, returncode=rc, finished_unix=now())
                item.pop("pid", None)
                save_item(root, item)
                archive_terminal(root, item)
                try:
                    live["stdout"].close()
                    live["stderr"].close()
                except Exception:
                    pass
                del active[item_id]

            if not paused and not draining and not global_cancel:
                while len(active) < max_active:
                    item = choose_queued(root)
                    if item is None:
                        break
                    manifest_path = Path(str(item["manifest"]))
                    try:
                        current_hash = sha256_file(manifest_path)
                    except OSError as exc:
                        item.update(status="failed", finished_unix=now(), failure_reason=f"manifest-unreadable: {exc}")
                        save_item(root, item)
                        archive_terminal(root, item)
                        continue
                    if current_hash != item.get("manifest_sha256"):
                        item.update(status="failed", finished_unix=now(), failure_reason="manifest-sha256-changed", observed_manifest_sha256=current_hash)
                        save_item(root, item)
                        archive_terminal(root, item)
                        continue
                    run_out = Path(str(item["run_out"]))
                    run_out.mkdir(parents=True, exist_ok=True)
                    cmd = tool_command(scheduler, item["manifest"], "--out", str(run_out))
                    if (run_out / "state.json").is_file():
                        cmd.append("--resume")
                    stdout_path = root / "logs" / f"{item['id']}.stdout.log"
                    stderr_path = root / "logs" / f"{item['id']}.stderr.log"
                    stdout = stdout_path.open("ab")
                    stderr = stderr_path.open("ab")
                    proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
                    item.update(
                        status="running", pid=proc.pid, started_unix=now(),
                        attempts=int(item.get("attempts", 0)) + 1,
                        command=cmd,
                    )
                    save_item(root, item)
                    active[str(item["id"])] = {"proc": proc, "stdout": stdout, "stderr": stderr}

            telemetry = write_telemetry(root, active)
            queued = int(telemetry["counts"].get("queued", 0))
            if draining and not active:
                break
            if global_cancel and not active:
                break
            if until_idle and queued == 0 and not active:
                break
            time.sleep(poll)
        write_telemetry(root, active)
        return 0
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
        lock.unlink(missing_ok=True)


def command_serve(ns: argparse.Namespace) -> int:
    root = ensure_root(ns.root)
    if ns.max_active < 1:
        raise ControlError("--max-active must be positive")
    if ns.poll_seconds <= 0:
        raise ControlError("--poll-seconds must be positive")
    scheduler = resolve_scheduler(ns.scheduler_tool)
    return serve(root, scheduler, int(ns.max_active), float(ns.poll_seconds), bool(ns.until_idle))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="initialize a persistent control-plane root")
    p.add_argument("root", type=Path)
    p.set_defaults(func=command_init)

    p = sub.add_parser("submit", help="submit a scheduler manifest to the persistent queue")
    p.add_argument("root", type=Path)
    p.add_argument("manifest", type=Path)
    p.add_argument("--id")
    p.add_argument("--priority", type=int, default=0)
    p.set_defaults(func=command_submit)

    p = sub.add_parser("serve", help="run the foreground control-plane supervisor")
    p.add_argument("root", type=Path)
    p.add_argument("--scheduler-tool")
    p.add_argument("--max-active", type=int, default=1)
    p.add_argument("--poll-seconds", type=float, default=0.1)
    p.add_argument("--until-idle", action="store_true")
    p.set_defaults(func=command_serve)

    p = sub.add_parser("status", help="show live queue/process/scheduler telemetry")
    p.add_argument("root", type=Path)
    p.add_argument("--json", action="store_true")
    p.add_argument("--watch", type=float, nargs="?", const=1.0)
    p.set_defaults(func=command_status)

    p = sub.add_parser("history", help="show persistent terminal run history")
    p.add_argument("root", type=Path)
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=command_history)

    for name, func in [("pause", command_pause), ("resume", command_resume), ("drain", command_drain)]:
        p = sub.add_parser(name)
        p.add_argument("root", type=Path)
        p.set_defaults(func=func)

    p = sub.add_parser("cancel")
    p.add_argument("root", type=Path)
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=command_cancel)
    return ap


def main() -> int:
    try:
        ns = build_parser().parse_args()
        return int(ns.func(ns))
    except (ControlError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ppc-lab-control: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
