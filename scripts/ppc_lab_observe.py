#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab LTS observability, health thresholds, and capacity planning.

The observability layer is intentionally dependency-free. It samples stable
PPC Lab control-plane JSON plus portable host metrics, stores immutable JSON
samples, and derives deterministic health/capacity reports. It never reads or
copies PPC target binaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

STORE_SCHEMA = "ppc-lab-observability-store-v1"
OBSERVATION_SCHEMA = "ppc-lab-observation-v1"
REPORT_SCHEMA = "ppc-lab-observability-report-v1"
POLICY_SCHEMA = "ppc-lab-observability-policy-v1"
CHECK_SCHEMA = "ppc-lab-observability-check-v1"
CAPACITY_SCHEMA = "ppc-lab-capacity-report-v1"
API_VERSION = 1

DEFAULT_POLICY: dict[str, Any] = {
    "schema": POLICY_SCHEMA,
    "observability_api": API_VERSION,
    "min_samples": 3,
    "queue_depth_warn": 4,
    "queue_depth_critical": 16,
    "queue_nonzero_fraction_warn": 0.50,
    "failure_rate_warn": 0.10,
    "failure_rate_critical": 0.25,
    "load_per_cpu_warn": 0.85,
    "load_per_cpu_critical": 1.25,
    "memory_available_ratio_warn": 0.15,
    "memory_available_ratio_critical": 0.08,
    "disk_free_ratio_warn": 0.15,
    "disk_free_ratio_critical": 0.08,
    "backlog_clear_hours_warn": 2.0,
    "backlog_clear_hours_critical": 8.0,
}


class ObserveError(RuntimeError):
    pass


def utc_iso(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def ensure_store(root: Path, *, create: bool) -> Path:
    root = root.expanduser().resolve()
    if root.exists() and root.is_symlink():
        raise ObserveError("observability store may not be a symlink")
    meta = root / "store.json"
    if not root.exists():
        if not create:
            raise ObserveError(f"observability store does not exist: {root}")
        (root / "samples").mkdir(parents=True)
        atomic_json(meta, {
            "schema": STORE_SCHEMA,
            "observability_api": API_VERSION,
            "created_unix": time.time(),
            "policy": "target-binaries-never-copied",
        })
    if not root.is_dir():
        raise ObserveError(f"observability store is not a directory: {root}")
    if not meta.is_file():
        raise ObserveError("observability store is missing store.json")
    doc = read_json(meta)
    if doc.get("schema") != STORE_SCHEMA:
        raise ObserveError(f"unsupported observability store schema: {doc.get('schema')}")
    (root / "samples").mkdir(exist_ok=True)
    return root


def resolve_control_tool(value: str | None) -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value).expanduser())
    found = shutil.which("ppc-lab-control")
    if found:
        candidates.append(Path(found))
    sibling = Path(__file__).resolve().parent
    candidates.extend([sibling / "ppc-lab-control", sibling / "ppc_lab_control.py"])
    for p in candidates:
        try:
            q = p.resolve()
        except OSError:
            continue
        if q.is_file():
            return q
    raise ObserveError("cannot find ppc-lab-control; use --control-tool")


def tool_cmd(tool: Path, *args: str) -> list[str]:
    return [sys.executable, str(tool), *args] if tool.suffix == ".py" else [str(tool), *args]


def run_json(cmd: list[str], *, timeout: float = 20.0) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ObserveError(f"command timed out: {' '.join(cmd)}") from exc
    if p.returncode != 0:
        raise ObserveError(p.stderr.strip() or p.stdout.strip() or f"command failed: {' '.join(cmd)}")
    try:
        doc = json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise ObserveError(f"command returned invalid JSON: {' '.join(cmd)}") from exc
    if not isinstance(doc, dict):
        raise ObserveError("command JSON response must be an object")
    return doc


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return float(vals[0])
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    return float(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo))


def runtime_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    durations: list[float] = []
    status_counts: dict[str, int] = {}
    for r in records:
        status = str(r.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        a = r.get("started_unix"); b = r.get("finished_unix")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b >= a:
            durations.append(float(b - a))
    return {
        "records": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "runtime_seconds": {
            "count": len(durations),
            "mean": statistics.fmean(durations) if durations else None,
            "p50": percentile(durations, 0.50),
            "p95": percentile(durations, 0.95),
            "max": max(durations) if durations else None,
        },
    }


def linux_memory() -> dict[str, Any] | None:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return None
    vals: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="ascii", errors="replace").splitlines():
            if ":" not in line:
                continue
            k, rest = line.split(":", 1)
            parts = rest.strip().split()
            if not parts:
                continue
            vals[k] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1)
    except (OSError, ValueError):
        return None
    total = vals.get("MemTotal"); avail = vals.get("MemAvailable")
    if not total or avail is None:
        return None
    return {"total_bytes": total, "available_bytes": avail, "available_ratio": avail / total}


def disk_metric(path: Path) -> dict[str, Any]:
    q = path.expanduser().resolve()
    probe = q
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {
        "path": str(q),
        "probe_path": str(probe),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "free_ratio": usage.free / usage.total if usage.total else None,
    }


def host_metrics(paths: Iterable[Path]) -> dict[str, Any]:
    cpus = os.cpu_count() or 1
    load = None
    try:
        l1, l5, l15 = os.getloadavg()
        load = {"one": l1, "five": l5, "fifteen": l15, "one_per_cpu": l1 / cpus}
    except (AttributeError, OSError):
        pass
    return {
        "cpu_count": cpus,
        "load": load,
        "memory": linux_memory(),
        "disks": [disk_metric(p) for p in paths],
    }


def collect(control_root: Path, control_tool: Path, *, slots: int | None, disk_paths: list[Path]) -> dict[str, Any]:
    control_root = control_root.expanduser().resolve()
    status = run_json(tool_cmd(control_tool, "status", str(control_root), "--json"))
    if status.get("schema") != "ppc-lab-control-telemetry-v1":
        raise ObserveError(f"unsupported control telemetry schema: {status.get('schema')}")
    history = run_json(tool_cmd(control_tool, "history", str(control_root), "--json"))
    if history.get("schema") != "ppc-lab-control-history-v1":
        raise ObserveError(f"unsupported control history schema: {history.get('schema')}")
    records = history.get("records", [])
    if not isinstance(records, list):
        raise ObserveError("control history records must be an array")
    paths = disk_paths or [control_root]
    now = time.time()
    return {
        "schema": OBSERVATION_SCHEMA,
        "observability_api": API_VERSION,
        "unix": now,
        "utc": utc_iso(now),
        "control": {
            "queue_depth": int(status.get("queue_depth", 0)),
            "history_count": int(status.get("history_count", 0)),
            "active_count": len(status.get("active", [])),
            "counts": status.get("counts", {}),
            "paused": bool(status.get("paused")),
            "draining": bool(status.get("draining")),
            "global_cancel": bool(status.get("global_cancel")),
            "history": runtime_summary([r for r in records if isinstance(r, dict)]),
            "configured_slots": slots,
        },
        "host": host_metrics(paths),
        "policy": {"target_binaries_copied": False, "private_inputs_read": False},
    }


def save_sample(store: Path, doc: dict[str, Any]) -> Path:
    if doc.get("schema") != OBSERVATION_SCHEMA:
        raise ObserveError("cannot store unsupported observation schema")
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    stamp = f"{int(float(doc.get('unix', time.time())) * 1_000_000):020d}"
    path = store / "samples" / f"{stamp}-{digest}.json"
    if not path.exists():
        atomic_json(path, doc)
    return path


def load_samples(store: Path, *, since_hours: float | None) -> list[dict[str, Any]]:
    cutoff = None if since_hours is None else time.time() - max(0.0, since_hours) * 3600.0
    out: list[dict[str, Any]] = []
    for p in sorted((store / "samples").glob("*.json")):
        try:
            d = read_json(p)
        except (OSError, json.JSONDecodeError) as exc:
            raise ObserveError(f"cannot read observation {p.name}: {exc}") from exc
        if d.get("schema") != OBSERVATION_SCHEMA:
            raise ObserveError(f"unsupported observation schema in {p.name}")
        ts = float(d.get("unix", 0.0))
        if cutoff is None or ts >= cutoff:
            out.append(d)
    out.sort(key=lambda d: float(d.get("unix", 0.0)))
    return out


def series(samples: list[dict[str, Any]], getter) -> list[float]:
    out: list[float] = []
    for s in samples:
        try:
            v = getter(s)
        except Exception:
            continue
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            out.append(float(v))
    return out


def stat_summary(vals: list[float]) -> dict[str, Any]:
    return {
        "count": len(vals),
        "mean": statistics.fmean(vals) if vals else None,
        "p50": percentile(vals, 0.50),
        "p95": percentile(vals, 0.95),
        "max": max(vals) if vals else None,
        "min": min(vals) if vals else None,
    }


def count_delta(first: dict[str, Any], last: dict[str, Any], key: str) -> int:
    a = int((first.get("control", {}).get("counts", {}) or {}).get(key, 0) or 0)
    b = int((last.get("control", {}).get("counts", {}) or {}).get(key, 0) or 0)
    return max(0, b - a)


def build_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise ObserveError("no observations in selected window")
    first, last = samples[0], samples[-1]
    elapsed = max(0.0, float(last["unix"]) - float(first["unix"]))
    hours = elapsed / 3600.0
    queues = series(samples, lambda s: s["control"]["queue_depth"])
    active = series(samples, lambda s: s["control"]["active_count"])
    load_cpu = series(samples, lambda s: (s.get("host", {}).get("load") or {}).get("one_per_cpu"))
    mem_avail = series(samples, lambda s: (s.get("host", {}).get("memory") or {}).get("available_ratio"))
    disk_free: list[float] = []
    for s in samples:
        for d in s.get("host", {}).get("disks", []) or []:
            v = d.get("free_ratio")
            if isinstance(v, (int, float)):
                disk_free.append(float(v))
    complete_delta = count_delta(first, last, "complete")
    failed_delta = count_delta(first, last, "failed")
    cancelled_delta = count_delta(first, last, "cancelled")
    terminal_delta = complete_delta + failed_delta + cancelled_delta
    throughput = complete_delta / hours if hours > 0 else None
    failure_rate = failed_delta / terminal_delta if terminal_delta else 0.0
    queue_nonzero = sum(1 for q in queues if q > 0) / len(queues) if queues else 0.0
    latest_history = last.get("control", {}).get("history", {}) or {}
    latest_runtime = latest_history.get("runtime_seconds", {}) or {}
    slots = last.get("control", {}).get("configured_slots")
    if not isinstance(slots, int) or slots <= 0:
        slots = None
    runtime_p50 = latest_runtime.get("p50")
    theoretical = None
    if slots and isinstance(runtime_p50, (int, float)) and runtime_p50 > 0:
        theoretical = slots * 3600.0 / float(runtime_p50)
    latest_queue = int(last.get("control", {}).get("queue_depth", 0))
    effective_rate = throughput if throughput and throughput > 0 else theoretical
    clear_hours = latest_queue / effective_rate if effective_rate and effective_rate > 0 else (0.0 if latest_queue == 0 else None)
    return {
        "schema": REPORT_SCHEMA,
        "observability_api": API_VERSION,
        "generated_unix": time.time(),
        "window": {"samples": len(samples), "start_unix": first["unix"], "end_unix": last["unix"], "elapsed_seconds": elapsed},
        "queue": {**stat_summary(queues), "nonzero_fraction": queue_nonzero, "latest": latest_queue},
        "active": {**stat_summary(active), "latest": int(last.get("control", {}).get("active_count", 0))},
        "terminal_delta": {"complete": complete_delta, "failed": failed_delta, "cancelled": cancelled_delta, "total": terminal_delta},
        "throughput": {"completed_per_hour": throughput, "failure_rate": failure_rate},
        "host": {
            "load_per_cpu": stat_summary(load_cpu),
            "memory_available_ratio": stat_summary(mem_avail),
            "disk_free_ratio": stat_summary(disk_free),
        },
        "service_time_seconds": latest_runtime,
        "capacity": {
            "configured_slots": slots,
            "theoretical_completed_per_hour_from_p50": theoretical,
            "estimated_backlog_clear_hours": clear_hours,
        },
        "policy": {"target_binaries_copied": False},
    }


def load_policy(path: Path | None) -> dict[str, Any]:
    p = dict(DEFAULT_POLICY)
    if path is None:
        return p
    doc = read_json(path.expanduser().resolve())
    if not isinstance(doc, dict) or doc.get("schema") != POLICY_SCHEMA:
        raise ObserveError(f"policy schema must be {POLICY_SCHEMA}")
    for k, v in doc.items():
        if k != "schema":
            p[k] = v
    p["schema"] = POLICY_SCHEMA
    return p


def health_check(report: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    samples = int(report["window"]["samples"])
    if samples < int(policy.get("min_samples", 3)):
        alerts.append({"severity": "warning", "metric": "samples", "value": samples, "threshold": policy.get("min_samples"), "message": "insufficient samples for stable trend judgement"})

    def upper(metric: str, value: float | None, warn: str, crit: str) -> None:
        if value is None:
            return
        if value >= float(policy[crit]):
            alerts.append({"severity": "critical", "metric": metric, "value": value, "threshold": policy[crit]})
        elif value >= float(policy[warn]):
            alerts.append({"severity": "warning", "metric": metric, "value": value, "threshold": policy[warn]})

    def lower(metric: str, value: float | None, warn: str, crit: str) -> None:
        if value is None:
            return
        if value <= float(policy[crit]):
            alerts.append({"severity": "critical", "metric": metric, "value": value, "threshold": policy[crit]})
        elif value <= float(policy[warn]):
            alerts.append({"severity": "warning", "metric": metric, "value": value, "threshold": policy[warn]})

    upper("queue.latest", report["queue"].get("latest"), "queue_depth_warn", "queue_depth_critical")
    qfrac = report["queue"].get("nonzero_fraction")
    if qfrac is not None and qfrac >= float(policy["queue_nonzero_fraction_warn"]):
        alerts.append({"severity": "warning", "metric": "queue.nonzero_fraction", "value": qfrac, "threshold": policy["queue_nonzero_fraction_warn"]})
    upper("throughput.failure_rate", report["throughput"].get("failure_rate"), "failure_rate_warn", "failure_rate_critical")
    upper("host.load_per_cpu.p95", report["host"]["load_per_cpu"].get("p95"), "load_per_cpu_warn", "load_per_cpu_critical")
    lower("host.memory_available_ratio.min", report["host"]["memory_available_ratio"].get("min"), "memory_available_ratio_warn", "memory_available_ratio_critical")
    lower("host.disk_free_ratio.min", report["host"]["disk_free_ratio"].get("min"), "disk_free_ratio_warn", "disk_free_ratio_critical")
    upper("capacity.estimated_backlog_clear_hours", report["capacity"].get("estimated_backlog_clear_hours"), "backlog_clear_hours_warn", "backlog_clear_hours_critical")
    severity = "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "ok"
    return {"schema": CHECK_SCHEMA, "observability_api": API_VERSION, "status": severity, "ok": severity != "critical", "alerts": alerts, "report": report}


def capacity_report(report: dict[str, Any], target_clear_hours: float) -> dict[str, Any]:
    if target_clear_hours <= 0:
        raise ObserveError("--target-clear-hours must be positive")
    latest_queue = int(report["queue"]["latest"])
    runtime = report.get("service_time_seconds", {}).get("p50")
    current_slots = report.get("capacity", {}).get("configured_slots")
    recommended = None
    per_slot = None
    if isinstance(runtime, (int, float)) and runtime > 0:
        per_slot = 3600.0 / float(runtime)
        recommended = max(1, math.ceil(latest_queue / (per_slot * target_clear_hours))) if latest_queue else 1
    observed = report.get("throughput", {}).get("completed_per_hour")
    notes: list[str] = []
    if runtime is None:
        notes.append("no completed-runtime median available; slot recommendation unavailable")
    if observed is None:
        notes.append("observation window is too short to compute observed throughput")
    if current_slots is None:
        notes.append("configured slot count was not supplied with observations")
    return {
        "schema": CAPACITY_SCHEMA,
        "observability_api": API_VERSION,
        "target_backlog_clear_hours": target_clear_hours,
        "latest_queue_depth": latest_queue,
        "current_slots": current_slots,
        "median_service_seconds": runtime,
        "estimated_jobs_per_hour_per_slot": per_slot,
        "observed_completed_per_hour": observed,
        "recommended_slots_for_current_backlog": recommended,
        "notes": notes,
    }


def emit(doc: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(doc, indent=2, sort_keys=True))
        return
    schema = doc.get("schema")
    if schema == REPORT_SCHEMA:
        print(f"samples={doc['window']['samples']} queue.latest={doc['queue']['latest']} queue.p95={doc['queue']['p95']}")
        print(f"throughput.completed_per_hour={doc['throughput']['completed_per_hour']} failure_rate={doc['throughput']['failure_rate']:.4f}")
        print(f"capacity.backlog_clear_hours={doc['capacity']['estimated_backlog_clear_hours']}")
    elif schema == CHECK_SCHEMA:
        print(f"health={doc['status']} alerts={len(doc['alerts'])}")
        for a in doc["alerts"]:
            print(f"{a['severity']}: {a['metric']} value={a.get('value')} threshold={a.get('threshold')}")
    elif schema == CAPACITY_SCHEMA:
        print(f"queue={doc['latest_queue_depth']} current_slots={doc['current_slots']} recommended_slots={doc['recommended_slots_for_current_backlog']}")
    else:
        print(json.dumps(doc, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="initialize an observability store")
    p.add_argument("store", type=Path)

    p = sub.add_parser("sample", help="capture one control-plane + host observation")
    p.add_argument("store", type=Path)
    p.add_argument("--control-root", type=Path, required=True)
    p.add_argument("--control-tool")
    p.add_argument("--slots", type=int)
    p.add_argument("--disk-path", type=Path, action="append", default=[])
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("report", help="summarize observations over a time window")
    p.add_argument("store", type=Path)
    p.add_argument("--since-hours", type=float)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("check", help="evaluate health thresholds")
    p.add_argument("store", type=Path)
    p.add_argument("--since-hours", type=float)
    p.add_argument("--policy", type=Path)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("capacity", help="estimate backlog-clearing capacity")
    p.add_argument("store", type=Path)
    p.add_argument("--since-hours", type=float)
    p.add_argument("--target-clear-hours", type=float, default=1.0)
    p.add_argument("--json", action="store_true")

    ns = ap.parse_args()
    try:
        if ns.cmd == "init":
            store = ensure_store(ns.store, create=True)
            print(json.dumps({"schema": STORE_SCHEMA, "store": str(store), "status": "initialized"}, sort_keys=True))
            return 0
        store = ensure_store(ns.store, create=(ns.cmd == "sample"))
        if ns.cmd == "sample":
            if ns.slots is not None and ns.slots <= 0:
                raise ObserveError("--slots must be positive")
            tool = resolve_control_tool(ns.control_tool)
            doc = collect(ns.control_root, tool, slots=ns.slots, disk_paths=ns.disk_path)
            path = save_sample(store, doc)
            result = {"schema": OBSERVATION_SCHEMA, "sample": str(path), "observation": doc}
            if ns.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(f"sample={path} queue={doc['control']['queue_depth']} active={doc['control']['active_count']}")
            return 0
        samples = load_samples(store, since_hours=ns.since_hours)
        report = build_report(samples)
        if ns.cmd == "report":
            emit(report, ns.json); return 0
        if ns.cmd == "check":
            check = health_check(report, load_policy(ns.policy)); emit(check, ns.json)
            return 0 if check["ok"] else 1
        cap = capacity_report(report, ns.target_clear_hours); emit(cap, ns.json); return 0
    except (OSError, ValueError, json.JSONDecodeError, ObserveError) as exc:
        print(f"ppc-lab-observe: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
