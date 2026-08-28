#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Automated differential triage for PPC Lab execution traces and jobs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

TRACE_SCHEMA = "ppc-lab-trace-v1"
TRIAGE_SCHEMA = "ppc-lab-differential-triage-v1"
BUNDLE_SCHEMA = "ppc-lab-triage-bundle-v1"
HEAD = re.compile(r"^(0x[0-9a-fA-F]{8})\s+(0x[0-9a-fA-F]{8})(?:\s+(.*))?$")
TAIL = re.compile(r"^(.*?)(?:\s+)?\[([^\]]+)\]$")

class TriageError(RuntimeError):
    pass

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TriageError(f"cannot read JSON {path}: {exc}") from exc

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def trace_event(line: str) -> dict[str, str] | None:
    m = HEAD.match(line)
    if not m:
        return None
    rest = (m.group(3) or "").strip()
    symbol = ""
    sm = TAIL.match(rest) if rest else None
    if sm:
        rest, symbol = sm.group(1).strip(), sm.group(2).strip()
    return {"pc": m.group(1).lower(), "instruction": m.group(2).lower(), "disassembly": rest, "symbol": symbol}

def trace_from_worker_response(response: dict[str, Any]) -> dict[str, Any]:
    events = []
    other = []
    for line in str(response.get("stderr", "")).splitlines():
        event = trace_event(line)
        if event:
            events.append(event)
        elif line.strip():
            other.append(line)
    return {
        "schema": TRACE_SCHEMA,
        "exit_code": response.get("exit_code"),
        "events": events,
        "stderr_unparsed": other,
        "stdout": response.get("stdout", ""),
    }

def ensure_trace(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != TRACE_SCHEMA or not isinstance(value.get("events"), list):
        raise TriageError(f"{label} must be {TRACE_SCHEMA}")
    return value

def sig(event: dict[str, Any]) -> tuple[str, str]:
    return str(event.get("pc", "")).lower(), str(event.get("instruction", "")).lower()

def compact_event(event: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "pc": event.get("pc"),
        "instruction": event.get("instruction"),
        "disassembly": event.get("disassembly", ""),
        "symbol": event.get("symbol", ""),
    }

def stable_snapshot_diff(left: Any, right: Any, path: str = "$", out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []
    ignored = {"backend", "format", "symbols"}
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key in ignored:
                continue
            if key not in left or key not in right:
                out.append({"path": f"{path}.{key}", "left": left.get(key, "<missing>"), "right": right.get(key, "<missing>")})
            else:
                stable_snapshot_diff(left[key], right[key], f"{path}.{key}", out)
        return out
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            out.append({"path": path + ".length", "left": len(left), "right": len(right)})
        for i, (a, b) in enumerate(zip(left, right)):
            stable_snapshot_diff(a, b, f"{path}[{i}]", out)
        return out
    if left != right:
        out.append({"path": path, "left": left, "right": right})
    return out

def classify(left_event: dict[str, Any] | None, right_event: dict[str, Any] | None) -> str:
    if left_event is None or right_event is None:
        return "trace-length"
    if left_event.get("pc") != right_event.get("pc"):
        return "control-flow"
    if left_event.get("instruction") != right_event.get("instruction"):
        return "instruction-bytes"
    return "dynamic-sequence"

def compare_traces(left: dict[str, Any], right: dict[str, Any], *, context: int = 6, snapshots: tuple[Any, Any] | None = None) -> dict[str, Any]:
    le = left["events"]
    revents = right["events"]
    ls = [sig(x) for x in le]
    rs = [sig(x) for x in revents]
    prefix = 0
    while prefix < min(len(ls), len(rs)) and ls[prefix] == rs[prefix]:
        prefix += 1
    trace_equal = ls == rs
    matcher = SequenceMatcher(a=ls, b=rs, autojunk=False)
    opcodes = matcher.get_opcodes()
    divergent_opcode = next((op for op in opcodes if op[0] != "equal"), None)
    resync = None
    if divergent_opcode is not None:
        _, li1, li2, ri1, ri2 = divergent_opcode
        for op in opcodes:
            tag, a1, a2, b1, b2 = op
            if tag == "equal" and a1 >= li2 and b1 >= ri2 and a2 > a1:
                resync = {"left_index": a1, "right_index": b1, "length": min(a2-a1, b2-b1), "pc": le[a1].get("pc") if a1 < len(le) else None}
                break
    left_first = le[prefix] if prefix < len(le) else None
    right_first = revents[prefix] if prefix < len(revents) else None
    classification = "equal" if trace_equal else classify(left_first, right_first)
    lstart = max(0, prefix - max(0, context))
    rstart = max(0, prefix - max(0, context))
    lend = min(len(le), (resync["left_index"] if resync else prefix + 1) + max(0, context) + 1)
    rend = min(len(revents), (resync["right_index"] if resync else prefix + 1) + max(0, context) + 1)
    report: dict[str, Any] = {
        "schema": TRIAGE_SCHEMA,
        "equal": trace_equal,
        "trace_equal": trace_equal,
        "classification": classification,
        "summary": {
            "left_events": len(le),
            "right_events": len(revents),
            "common_prefix_events": prefix,
            "left_unique_pcs": len({x.get("pc") for x in le}),
            "right_unique_pcs": len({x.get("pc") for x in revents}),
        },
        "first_divergence": None if trace_equal else {
            "left": compact_event(left_first, prefix) if left_first else None,
            "right": compact_event(right_first, prefix) if right_first else None,
        },
        "resynchronization": resync,
        "window": {
            "left": [compact_event(x, i) for i, x in enumerate(le[lstart:lend], start=lstart)],
            "right": [compact_event(x, i) for i, x in enumerate(revents[rstart:rend], start=rstart)],
        },
        "alignment": [
            {"kind": tag, "left": [a1, a2], "right": [b1, b2]}
            for tag, a1, a2, b1, b2 in opcodes
            if tag != "equal" or (a1 <= prefix <= a2)
        ][:32],
    }
    if snapshots is not None:
        left_snapshot, right_snapshot = snapshots
        if isinstance(left_snapshot, dict) and isinstance(right_snapshot, dict):
            sd = stable_snapshot_diff(left_snapshot, right_snapshot)
            state_equal = not sd
            report["snapshot"] = {"equal": state_equal, "differences": sd[:256], "difference_count": len(sd)}
            if not state_equal:
                report["equal"] = False
                if trace_equal:
                    report["classification"] = "state-only"
    return report

def resolve_program(value: str, label: str) -> Path:
    found = shutil.which(value) or value
    path = Path(found).expanduser().resolve()
    if not path.is_file():
        raise TriageError(f"cannot find {label}: {value}")
    return path

def run_worker(job: dict[str, Any], *, job_base: Path, cli: Path, worker: Path, root: Path | None, timeout: float) -> dict[str, Any]:
    cmd = [sys.executable, str(worker), "--ppc-lab", str(cli), "--base-dir", str(job_base), "--timeout", str(timeout)]
    if root is not None:
        cmd += ["--root", str(root)]
    cmd += ["run", "-"]
    p = subprocess.run(cmd, input=json.dumps(job), text=True, capture_output=True, timeout=timeout + 5, check=False)
    try:
        response = json.loads(p.stdout)
    except Exception as exc:
        raise TriageError(f"worker returned invalid JSON ({label if (label := cli.name) else 'worker'}): {p.stdout[:300]} {p.stderr[:300]}") from exc
    return response

def job_input_provenance(job: dict[str, Any], base: Path, root: Path | None = None) -> list[dict[str, Any]]:
    out = []
    image = job.get("image", {}) if isinstance(job.get("image"), dict) else {}
    for field in ("path", "data_path"):
        raw = image.get(field)
        if not isinstance(raw, str):
            continue
        p = Path(raw)
        p = (base / p if not p.is_absolute() else p).resolve()
        if root is not None:
            try:
                p.relative_to(root.resolve())
            except ValueError as exc:
                raise TriageError(f"image.{field} is outside triage root: {p}") from exc
        if p.is_file():
            out.append({"field": f"image.{field}", "path": raw, "size": p.stat().st_size, "sha256": sha256_file(p)})
    return out

def write_bundle(bundle: Path, report: dict[str, Any], left_trace: dict[str, Any], right_trace: dict[str, Any], *, job: dict[str, Any] | None = None, responses: tuple[Any, Any] | None = None) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    write_json(bundle / "triage.json", report)
    write_json(bundle / "left.trace.json", left_trace)
    write_json(bundle / "right.trace.json", right_trace)
    manifest: dict[str, Any] = {"schema": BUNDLE_SCHEMA, "triage": "triage.json", "left_trace": "left.trace.json", "right_trace": "right.trace.json"}
    if job is not None:
        repro = copy.deepcopy(job)
        if not report.get("equal"):
            execution = repro.setdefault("execution", {})
            previous = execution.get("max_instructions")
            reduced = max(1, int(report["summary"]["common_prefix_events"]) + 8)
            try:
                previous_int = int(str(previous), 0) if previous is not None else 0
            except (TypeError, ValueError):
                previous_int = 0
            if previous_int > 0:
                reduced = min(reduced, previous_int)
            execution["max_instructions"] = reduced
            execution["trace"] = True
        write_json(bundle / "repro.job.json", repro)
        manifest["repro_job"] = "repro.job.json"
    if responses is not None:
        write_json(bundle / "left.response.json", responses[0])
        write_json(bundle / "right.response.json", responses[1])
        manifest["left_response"] = "left.response.json"
        manifest["right_response"] = "right.response.json"
    write_json(bundle / "manifest.json", manifest)
    div = report.get("first_divergence")
    lines = ["# PPC Lab differential triage bundle", "", f"Equal: `{str(report.get('equal')).lower()}`", f"Classification: `{report.get('classification')}`", f"Common prefix: `{report.get('summary',{}).get('common_prefix_events',0)}` events"]
    if div:
        lines += ["", "## First divergence", "", f"- left: `{div.get('left')}`", f"- right: `{div.get('right')}`"]
    if report.get("resynchronization"):
        lines += ["", f"Resynchronizes at: `{report['resynchronization']}`"]
    lines += ["", "Target binaries are not copied into this bundle.", ""]
    (bundle / "README.md").write_text("\n".join(lines), encoding="utf-8")

def command_compare(ns: argparse.Namespace) -> int:
    left = ensure_trace(read_json(ns.left), "left trace")
    right = ensure_trace(read_json(ns.right), "right trace")
    snapshots = None
    if ns.left_snapshot or ns.right_snapshot:
        if not ns.left_snapshot or not ns.right_snapshot:
            raise TriageError("both --left-snapshot and --right-snapshot are required together")
        snapshots = (read_json(ns.left_snapshot), read_json(ns.right_snapshot))
    report = compare_traces(left, right, context=ns.context, snapshots=snapshots)
    if ns.json:
        write_json(ns.json, report)
    if ns.bundle:
        write_bundle(ns.bundle, report, left, right)
    print(f"equal={str(report['equal']).lower()} classification={report['classification']} common_prefix={report['summary']['common_prefix_events']} left_events={report['summary']['left_events']} right_events={report['summary']['right_events']}")
    if report.get("first_divergence"):
        d = report["first_divergence"]
        print(f"left_first={d.get('left')}\nright_first={d.get('right')}")
    if report.get("resynchronization"):
        r = report["resynchronization"]
        print(f"resync=left:{r['left_index']} right:{r['right_index']} pc:{r.get('pc')}")
    return 1 if ns.fail_on_diff and not report["equal"] else 0

def command_run(ns: argparse.Namespace) -> int:
    job_path = ns.job.resolve()
    job = read_json(job_path)
    if not isinstance(job, dict) or job.get("schema") != "ppc-lab-job-v1":
        raise TriageError("job must use ppc-lab-job-v1")
    left_job = copy.deepcopy(job)
    right_job = copy.deepcopy(job)
    left_job.setdefault("execution", {})["backend"] = ns.left_backend
    right_job.setdefault("execution", {})["backend"] = ns.right_backend
    left_job["execution"]["trace"] = True
    right_job["execution"]["trace"] = True
    left_cli = resolve_program(ns.left_ppc_lab, "left ppc-lab")
    right_cli = resolve_program(ns.right_ppc_lab or ns.left_ppc_lab, "right ppc-lab")
    left_worker = resolve_program(ns.left_worker, "left worker")
    right_worker = resolve_program(ns.right_worker or ns.left_worker, "right worker")
    root = ns.root.resolve() if ns.root else None
    left_response = run_worker(left_job, job_base=job_path.parent, cli=left_cli, worker=left_worker, root=root, timeout=ns.timeout)
    right_response = run_worker(right_job, job_base=job_path.parent, cli=right_cli, worker=right_worker, root=root, timeout=ns.timeout)
    left_trace = ensure_trace(trace_from_worker_response(left_response), "left trace")
    right_trace = ensure_trace(trace_from_worker_response(right_response), "right trace")
    report = compare_traces(left_trace, right_trace, context=ns.context, snapshots=(left_response.get("snapshot"), right_response.get("snapshot")))
    report["run"] = {
        "left": {"engine": str(left_cli), "backend": ns.left_backend, "ok": left_response.get("ok"), "exit_code": left_response.get("exit_code")},
        "right": {"engine": str(right_cli), "backend": ns.right_backend, "ok": right_response.get("ok"), "exit_code": right_response.get("exit_code")},
        "inputs": job_input_provenance(job, job_path.parent, root),
    }
    lo = (left_response.get("ok"), left_response.get("exit_code"), left_response.get("timed_out", False))
    ro = (right_response.get("ok"), right_response.get("exit_code"), right_response.get("timed_out", False))
    report["run"]["outcome_equal"] = lo == ro
    if lo != ro:
        report["equal"] = False
        if report["classification"] == "equal":
            report["classification"] = "worker-outcome"
    if ns.json:
        write_json(ns.json, report)
    if ns.bundle:
        write_bundle(ns.bundle, report, left_trace, right_trace, job=job, responses=(left_response, right_response))
    print(f"equal={str(report['equal']).lower()} classification={report['classification']} common_prefix={report['summary']['common_prefix_events']} left={ns.left_backend} right={ns.right_backend}")
    if report.get("first_divergence"):
        print(f"first_divergence={json.dumps(report['first_divergence'], sort_keys=True)}")
    return 1 if ns.fail_on_diff and not report["equal"] else 0

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("compare", help="triage two existing ppc-lab-trace-v1 files")
    p.add_argument("left", type=Path); p.add_argument("right", type=Path)
    p.add_argument("--left-snapshot", type=Path); p.add_argument("--right-snapshot", type=Path)
    p.add_argument("--context", type=int, default=6); p.add_argument("--json", type=Path); p.add_argument("--bundle", type=Path); p.add_argument("--fail-on-diff", action="store_true")
    p = sub.add_parser("run", help="run one ppc-lab-job-v1 against two engines/backends and triage")
    p.add_argument("job", type=Path); p.add_argument("--left-ppc-lab", default="ppc-lab"); p.add_argument("--right-ppc-lab")
    p.add_argument("--left-worker", default="ppc-lab-worker"); p.add_argument("--right-worker")
    p.add_argument("--left-backend", choices=["auto", "builtin", "unicorn"], default="builtin"); p.add_argument("--right-backend", choices=["auto", "builtin", "unicorn"], default="auto")
    p.add_argument("--root", type=Path); p.add_argument("--timeout", type=float, default=60.0); p.add_argument("--context", type=int, default=6); p.add_argument("--json", type=Path); p.add_argument("--bundle", type=Path); p.add_argument("--fail-on-diff", action="store_true")
    ns = ap.parse_args()
    if getattr(ns, "context", 0) < 0:
        ap.error("--context must be non-negative")
    if getattr(ns, "timeout", 1) <= 0:
        ap.error("--timeout must be positive")
    try:
        return command_compare(ns) if ns.cmd == "compare" else command_run(ns)
    except (TriageError, subprocess.TimeoutExpired) as exc:
        print(f"ppc-lab-triage: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
