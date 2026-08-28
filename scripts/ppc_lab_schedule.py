#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic campaign scheduler and resource governor for PPC Lab.

The scheduler composes the installed ppc-lab-campaign command.  It does not
change campaign semantics; it governs which campaigns are admitted, when they
run, and how project-level budgets/concurrency are shared.
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
import time
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ppc-lab-scheduler-v1"
STATE_SCHEMA = "ppc-lab-scheduler-state-v1"
SUMMARY_SCHEMA = "ppc-lab-scheduler-summary-v1"
TERMINAL = {"complete", "failed", "cancelled", "quota-blocked"}


class SchedulerError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve_tool(value: str | None, name: str) -> Path:
    candidate = value or shutil.which(name)
    if not candidate:
        raise SchedulerError(f"cannot find {name}; use --campaign-tool")
    p = Path(candidate).expanduser().resolve()
    if not p.is_file():
        raise SchedulerError(f"campaign tool is not a file: {p}")
    return p


def tool_command(tool: Path, *args: str) -> list[str]:
    return [sys.executable, str(tool), *args] if tool.suffix == ".py" else [str(tool), *args]


def validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in value):
        raise SchedulerError(f"{label} must be a non-empty portable identifier")
    return value


def positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    try:
        n = int(value)
    except Exception as exc:
        raise SchedulerError(f"{label} must be an integer") from exc
    if n < (0 if allow_zero else 1):
        raise SchedulerError(f"{label} must be {'non-negative' if allow_zero else 'positive'}")
    return n


def positive_float(value: Any, label: str) -> float:
    try:
        n = float(value)
    except Exception as exc:
        raise SchedulerError(f"{label} must be a number") from exc
    if n <= 0:
        raise SchedulerError(f"{label} must be positive")
    return n


def validate_manifest(doc: Any, base: Path, out: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], int]:
    if not isinstance(doc, dict) or doc.get("schema") != MANIFEST_SCHEMA:
        raise SchedulerError(f"scheduler schema must be {MANIFEST_SCHEMA}")
    global_cfg = doc.get("resources", {})
    if not isinstance(global_cfg, dict):
        raise SchedulerError("resources must be an object")
    global_max = positive_int(global_cfg.get("max_concurrent", 1), "resources.max_concurrent")

    raw_projects = doc.get("projects")
    if not isinstance(raw_projects, list) or not raw_projects:
        raise SchedulerError("projects must be a non-empty array")
    projects: dict[str, dict[str, Any]] = {}
    for order, raw in enumerate(raw_projects):
        if not isinstance(raw, dict):
            raise SchedulerError("each project must be an object")
        pid = validate_id(raw.get("id"), "project.id")
        if pid in projects:
            raise SchedulerError(f"duplicate project id: {pid}")
        weight = positive_int(raw.get("weight", 1), f"project {pid} weight")
        max_concurrent = positive_int(raw.get("max_concurrent", global_max), f"project {pid} max_concurrent")
        case_budget = raw.get("case_budget")
        wall_budget = raw.get("wall_seconds")
        projects[pid] = {
            "id": pid,
            "order": order,
            "weight": weight,
            "max_concurrent": max_concurrent,
            "case_budget": None if case_budget is None else positive_int(case_budget, f"project {pid} case_budget", allow_zero=True),
            "wall_seconds": None if wall_budget is None else positive_float(wall_budget, f"project {pid} wall_seconds"),
        }

    raw_campaigns = doc.get("campaigns")
    if not isinstance(raw_campaigns, list) or not raw_campaigns:
        raise SchedulerError("campaigns must be a non-empty array")
    campaigns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, raw in enumerate(raw_campaigns):
        if not isinstance(raw, dict):
            raise SchedulerError("each campaign must be an object")
        cid = validate_id(raw.get("id"), "campaign.id")
        if cid in seen:
            raise SchedulerError(f"duplicate campaign id: {cid}")
        seen.add(cid)
        pid = validate_id(raw.get("project"), f"campaign {cid} project")
        if pid not in projects:
            raise SchedulerError(f"campaign {cid} references unknown project {pid}")
        mraw = raw.get("manifest")
        if not isinstance(mraw, str) or not mraw:
            raise SchedulerError(f"campaign {cid} manifest must be a path string")
        manifest = Path(mraw).expanduser()
        if not manifest.is_absolute():
            manifest = base / manifest
        manifest = manifest.resolve()
        if not manifest.is_file():
            raise SchedulerError(f"campaign {cid} manifest missing: {manifest}")
        oraw = raw.get("out")
        campaign_out = (out / "campaigns" / cid) if oraw is None else Path(str(oraw)).expanduser()
        if not campaign_out.is_absolute():
            campaign_out = out / campaign_out
        campaign_out = campaign_out.resolve()
        priority = int(raw.get("priority", 0))
        reserve_cases = positive_int(raw.get("reserve_cases", 0), f"campaign {cid} reserve_cases", allow_zero=True)
        wall_seconds = raw.get("wall_seconds")
        campaigns.append({
            "id": cid,
            "project": pid,
            "manifest": str(manifest),
            "out": str(campaign_out),
            "priority": priority,
            "reserve_cases": reserve_cases,
            "wall_seconds": None if wall_seconds is None else positive_float(wall_seconds, f"campaign {cid} wall_seconds"),
            "order": order,
        })
    return projects, campaigns, global_max


def new_state(manifest_hash: str, projects: dict[str, dict[str, Any]], campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "manifest_sha256": manifest_hash,
        "created_unix": time.time(),
        "projects": {
            pid: {
                "weight": p["weight"], "max_concurrent": p["max_concurrent"],
                "case_budget": p["case_budget"], "wall_seconds": p["wall_seconds"],
                "reserved_cases": 0, "elapsed_seconds": 0.0, "dispatched": 0,
            } for pid, p in projects.items()
        },
        "campaigns": {
            c["id"]: {
                "id": c["id"], "project": c["project"], "priority": c["priority"],
                "reserve_cases": c["reserve_cases"], "manifest": c["manifest"], "out": c["out"],
                "status": "pending", "attempts": 0,
            } for c in campaigns
        },
        "events": [],
    }


def load_state(path: Path, manifest_hash: str, projects: dict[str, dict[str, Any]], campaigns: list[dict[str, Any]], resume: bool) -> dict[str, Any]:
    if path.exists():
        if not resume:
            raise SchedulerError("scheduler state exists; use --resume or a new --out directory")
        state = read_json(path)
        if state.get("schema") != STATE_SCHEMA or state.get("manifest_sha256") != manifest_hash:
            raise SchedulerError("scheduler manifest changed since checkpoint; use a new --out directory")
        # Resume is exact: terminal admission decisions are immutable.  Only
        # interrupted/running work becomes pending again.
        for rec in state.get("campaigns", {}).values():
            if rec.get("status") == "running":
                rec["status"] = "pending"
                rec.pop("pid", None)
        return state
    if resume:
        raise SchedulerError("--resume requested but scheduler state does not exist")
    return new_state(manifest_hash, projects, campaigns)


def event(state: dict[str, Any], kind: str, campaign: str | None = None, **extra: Any) -> None:
    rec = {"seq": len(state["events"]), "kind": kind, "unix": time.time(), **extra}
    if campaign is not None:
        rec["campaign"] = campaign
    state["events"].append(rec)


def choose_next(campaigns: list[dict[str, Any]], state: dict[str, Any], projects: dict[str, dict[str, Any]], running_by_project: dict[str, int]) -> dict[str, Any] | None:
    eligible_projects: list[tuple[float, int, str]] = []
    for pid, p in projects.items():
        if running_by_project.get(pid, 0) >= p["max_concurrent"]:
            continue
        pending = [c for c in campaigns if c["project"] == pid and state["campaigns"][c["id"]]["status"] == "pending"]
        if not pending:
            continue
        ps = state["projects"][pid]
        eligible_projects.append((ps["dispatched"] / float(p["weight"]), p["order"], pid))
    if not eligible_projects:
        return None
    _, _, pid = min(eligible_projects)
    pending = [c for c in campaigns if c["project"] == pid and state["campaigns"][c["id"]]["status"] == "pending"]
    return min(pending, key=lambda c: (-c["priority"], c["order"], c["id"]))


def quota_allows(c: dict[str, Any], state: dict[str, Any], projects: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    pid = c["project"]
    p = projects[pid]
    ps = state["projects"][pid]
    if p["case_budget"] is not None and ps["reserved_cases"] + c["reserve_cases"] > p["case_budget"]:
        return False, "project-case-budget"
    if p["wall_seconds"] is not None and ps["elapsed_seconds"] >= p["wall_seconds"]:
        return False, "project-wall-budget"
    return True, None


def terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def summary(state: dict[str, Any], drained: bool) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for rec in state["campaigns"].values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    if drained and counts.get("pending", 0):
        status = "drained"
    elif counts.get("running", 0) or counts.get("pending", 0):
        status = "incomplete"
    elif counts.get("failed", 0) or counts.get("cancelled", 0):
        status = "complete-with-failures"
    else:
        status = "complete"
    return {
        "schema": SUMMARY_SCHEMA,
        "status": status,
        "counts": dict(sorted(counts.items())),
        "projects": state["projects"],
        "campaigns": [state["campaigns"][k] for k in sorted(state["campaigns"])],
        "events": state["events"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--campaign-tool")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--poll-seconds", type=float, default=0.05)
    ns = ap.parse_args()
    try:
        if ns.poll_seconds <= 0:
            raise SchedulerError("--poll-seconds must be positive")
        manifest_path = ns.manifest.expanduser().resolve(strict=True)
        out = ns.out.expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        projects, campaigns, global_max = validate_manifest(read_json(manifest_path), manifest_path.parent, out)
        tool = resolve_tool(ns.campaign_tool, "ppc-lab-campaign")
        manifest_hash = sha256_file(manifest_path)
        state_path = out / "state.json"
        state = load_state(state_path, manifest_hash, projects, campaigns, ns.resume)
        write_json(state_path, state)
        cancel_dir = out / "cancel"
        cancel_dir.mkdir(exist_ok=True)
        drain_marker = out / "DRAIN"
        cancel_all_marker = out / "CANCEL"

        running: dict[str, dict[str, Any]] = {}
        drained = False
        while True:
            # Observe cancellation first so no new work starts after a stop request.
            if cancel_all_marker.exists():
                for cid, item in list(running.items()):
                    terminate(item["proc"])
                    rec = state["campaigns"][cid]
                    elapsed = time.monotonic() - item["started"]
                    rec.update(status="cancelled", elapsed_seconds=round(elapsed, 6), returncode=item["proc"].returncode)
                    state["projects"][rec["project"]]["elapsed_seconds"] += elapsed
                    event(state, "cancelled", cid, reason="global-cancel")
                    del running[cid]
                for rec in state["campaigns"].values():
                    if rec["status"] == "pending":
                        rec["status"] = "cancelled"
                        event(state, "cancelled", rec["id"], reason="global-cancel-before-start")
                write_json(state_path, state)
                break

            for cid, item in list(running.items()):
                rec = state["campaigns"][cid]
                project = projects[rec["project"]]
                marker = cancel_dir / cid
                wall_limit = item["wall_seconds"]
                elapsed = time.monotonic() - item["started"]
                if marker.exists() or (wall_limit is not None and elapsed >= wall_limit):
                    terminate(item["proc"])
                    reason = "campaign-cancel-marker" if marker.exists() else "campaign-wall-limit"
                    rec.update(status="cancelled", elapsed_seconds=round(elapsed, 6), returncode=item["proc"].returncode)
                    state["projects"][rec["project"]]["elapsed_seconds"] += elapsed
                    event(state, "cancelled", cid, reason=reason)
                    del running[cid]
                    write_json(state_path, state)
                    continue
                rc = item["proc"].poll()
                if rc is not None:
                    elapsed = time.monotonic() - item["started"]
                    rec.update(status="complete" if rc == 0 else "failed", returncode=rc, elapsed_seconds=round(elapsed, 6))
                    state["projects"][rec["project"]]["elapsed_seconds"] += elapsed
                    event(state, "finished", cid, returncode=rc, status=rec["status"])
                    del running[cid]
                    write_json(state_path, state)

            if drain_marker.exists():
                drained = True
            if drained and not running:
                break

            running_by_project: dict[str, int] = {}
            for cid in running:
                pid = state["campaigns"][cid]["project"]
                running_by_project[pid] = running_by_project.get(pid, 0) + 1

            launched = False
            while not drained and len(running) < global_max:
                c = choose_next(campaigns, state, projects, running_by_project)
                if c is None:
                    break
                rec = state["campaigns"][c["id"]]
                marker = cancel_dir / c["id"]
                if marker.exists():
                    rec["status"] = "cancelled"
                    event(state, "cancelled", c["id"], reason="campaign-cancel-marker-before-start")
                    write_json(state_path, state)
                    continue
                allowed, reason = quota_allows(c, state, projects)
                if not allowed:
                    # Admission decisions are terminal and survive --resume.
                    rec.update(status="quota-blocked", reason=reason)
                    event(state, "quota-blocked", c["id"], reason=reason)
                    write_json(state_path, state)
                    continue
                cmd = tool_command(tool, c["manifest"], "--out", c["out"])
                if Path(c["out"]).joinpath("state.json").exists():
                    cmd.append("--resume")
                proc = subprocess.Popen(cmd, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                rec.update(status="running", pid=proc.pid, attempts=int(rec.get("attempts", 0)) + 1, command=cmd)
                ps = state["projects"][c["project"]]
                ps["reserved_cases"] += c["reserve_cases"]
                ps["dispatched"] += 1
                running[c["id"]] = {"proc": proc, "started": time.monotonic(), "wall_seconds": c["wall_seconds"]}
                running_by_project[c["project"]] = running_by_project.get(c["project"], 0) + 1
                event(state, "started", c["id"], project=c["project"], priority=c["priority"], reserve_cases=c["reserve_cases"])
                write_json(state_path, state)
                launched = True

            pending = any(rec["status"] == "pending" for rec in state["campaigns"].values())
            if not running and not pending:
                break
            if not running and pending and not launched:
                # Pending work with no launchable slot should be impossible after quota
                # admission is resolved; fail visibly rather than spin forever.
                raise SchedulerError("scheduler deadlock: pending campaigns but no launchable work")
            time.sleep(ns.poll_seconds)

        final = summary(state, drained)
        write_json(out / "summary.json", final)
        print(json.dumps(final, sort_keys=True))
        return 0 if final["status"] in {"complete", "drained"} else 1
    except (SchedulerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ppc-lab-schedule: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
