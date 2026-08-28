#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic guided exploration and behavioral-corpus synthesis for PPC Lab."""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import re
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ppc-lab-exploration-v1"
CASE_SCHEMA = "ppc-lab-exploration-case-v1"
SUMMARY_SCHEMA = "ppc-lab-exploration-summary-v1"
TRACE_HEAD = re.compile(r"^(0x[0-9a-fA-F]{8})\s+(0x[0-9a-fA-F]{8})(?:\s+.*)?$")
ALLOWED_AXIS_ROOTS = {"registers", "float_registers", "writes_u32", "writes_f32", "bindings", "syscall_returns"}


class ExploreError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()


def contained(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ExploreError(f"input is outside exploration root: {resolved}") from exc
    if not resolved.is_file():
        raise ExploreError(f"input is not a file: {resolved}")
    return resolved


def resolve_inputs(job: dict[str, Any], base_dir: Path, root: Path) -> list[dict[str, Any]]:
    image = job.get("image")
    if not isinstance(image, dict):
        raise ExploreError("base_job.image must be an object")
    out = []
    for field in ("path", "data_path"):
        raw = image.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw:
            raise ExploreError(f"base_job.image.{field} must be a non-empty path")
        p = Path(raw)
        if not p.is_absolute():
            p = base_dir / p
        p = contained(p, root)
        out.append({"field": f"image.{field}", "path": str(p), "size": p.stat().st_size, "sha256": sha256_file(p)})
    if not out:
        raise ExploreError("base_job.image.path is required")
    return out


def validate_axis(axis: Any, index: int) -> tuple[str, list[Any]]:
    if not isinstance(axis, dict):
        raise ExploreError(f"axes[{index}] must be an object")
    path = axis.get("path")
    values = axis.get("values")
    if not isinstance(path, str) or "." not in path:
        raise ExploreError(f"axes[{index}].path must be FIELD.KEY")
    root = path.split(".", 1)[0]
    if root not in ALLOWED_AXIS_ROOTS:
        raise ExploreError(f"axes[{index}].path cannot mutate structural field {path!r}")
    if not isinstance(values, list) or not values:
        raise ExploreError(f"axes[{index}].values must be a non-empty array")
    return path, values


def set_path(job: dict[str, Any], path: str, value: Any) -> None:
    first, second = path.split(".", 1)
    obj = job.setdefault(first, {})
    if not isinstance(obj, dict):
        raise ExploreError(f"base_job.{first} must be an object to mutate {path}")
    obj[second] = copy.deepcopy(value)


def assignment_key(assignment: dict[str, Any]) -> str:
    return json.dumps(assignment, sort_keys=True, separators=(",", ":"))


def trace_pcs(stderr: str) -> list[str]:
    pcs = []
    for line in stderr.splitlines():
        m = TRACE_HEAD.match(line.strip())
        if m:
            pcs.append(m.group(1).lower())
    return pcs


def _u32(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return int(value) & 0xFFFFFFFF
        if isinstance(value, int):
            return value & 0xFFFFFFFF
        if isinstance(value, str):
            return int(value, 0) & 0xFFFFFFFF
    except (TypeError, ValueError):
        pass
    return None


def stable_architecture(response: dict[str, Any], assignment: dict[str, Any] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "ok": response.get("ok"),
        "exit_code": response.get("exit_code"),
        "timed_out": response.get("timed_out", False),
    }
    if response.get("error") is not None:
        value["error"] = response.get("error")
    result = response.get("result")
    if isinstance(result, dict):
        value["result"] = {k: copy.deepcopy(result[k]) for k in (
            "stop_reason", "instructions", "pc", "instruction", "registers", "lr", "ctr", "cr", "dumps"
        ) if k in result}
    snapshot = response.get("snapshot")
    if isinstance(snapshot, dict):
        value["snapshot"] = {k: copy.deepcopy(snapshot[k]) for k in (
            "stop_reason", "instructions", "pc", "instruction", "cpu", "regions", "dumps"
        ) if k in snapshot}

    # Do not classify a case as behaviorally novel merely because an explored
    # input register still contains the value PPC Lab placed there. Unchanged
    # input GPRs are replaced with a stable sentinel in both result/snapshot
    # views before hashing. If guest code changes the register, the changed
    # output remains part of the behavioral fingerprint.
    for path, input_value in (assignment or {}).items():
        if not isinstance(path, str) or not path.startswith("registers.r"):
            continue
        name = path.split(".", 1)[1]
        try:
            index = int(name[1:])
        except (ValueError, IndexError):
            continue
        expected = _u32(input_value)
        if expected is None or not 0 <= index < 32:
            continue
        result_regs = value.get("result", {}).get("registers") if isinstance(value.get("result"), dict) else None
        if isinstance(result_regs, dict) and _u32(result_regs.get(name)) == expected:
            result_regs[name] = "<input>"
        cpu = value.get("snapshot", {}).get("cpu") if isinstance(value.get("snapshot"), dict) else None
        gpr = cpu.get("gpr") if isinstance(cpu, dict) else None
        if isinstance(gpr, list) and index < len(gpr) and _u32(gpr[index]) == expected:
            gpr[index] = "<input>"
    return value


def find_tool(value: str | None, default: str) -> Path:
    candidate = value or shutil.which(default)
    if not candidate:
        raise ExploreError(f"cannot find {default}; use the explicit tool option")
    p = Path(candidate).expanduser().resolve()
    if not p.is_file():
        raise ExploreError(f"tool is not a file: {p}")
    return p


def run_worker(job: dict[str, Any], *, cli: Path, worker: Path, base_dir: Path, root: Path, timeout: float) -> dict[str, Any]:
    execution = job.setdefault("execution", {})
    if not isinstance(execution, dict):
        raise ExploreError("base_job.execution must be an object")
    execution["trace"] = True
    command = [sys.executable, str(worker), "--ppc-lab", str(cli), "--root", str(root), "--base-dir", str(base_dir), "--timeout", str(timeout), "run", "-"]
    try:
        p = subprocess.run(command, input=json.dumps(job), text=True, capture_output=True, timeout=timeout + 5.0, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ExploreError(f"worker transport timeout after {timeout + 5.0:g}s") from exc
    try:
        response = json.loads(p.stdout)
    except Exception as exc:
        raise ExploreError(f"worker returned invalid JSON: {p.stdout[:200]} {p.stderr[:200]}") from exc
    return response


def job_with_assignment(base_job: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    job = copy.deepcopy(base_job)
    for path, value in assignment.items():
        set_path(job, path, value)
    return job


def absolute_job_inputs(job: dict[str, Any], base_dir: Path, root: Path) -> dict[str, Any]:
    out = copy.deepcopy(job)
    image = out.get("image", {})
    for field in ("path", "data_path"):
        raw = image.get(field)
        if raw is None:
            continue
        p = Path(raw)
        if not p.is_absolute():
            p = base_dir / p
        image[field] = str(contained(p, root))
    return out


def promote(corpus: Path, case_id: str, job: dict[str, Any], *, cli: Path, worker: Path, corpus_tool: Path,
            base_dir: Path, root: Path, timeout: float) -> None:
    with __import__("tempfile").TemporaryDirectory(prefix="ppclab-explore-promote-") as td_text:
        td = Path(td_text)
        jp = td / "job.json"
        write_json(jp, absolute_job_inputs(job, base_dir, root))
        cmd = [sys.executable, str(corpus_tool), "--ppc-lab", str(cli), "--worker", str(worker), "--timeout", str(timeout),
               "promote", str(corpus), "--id", case_id, "--job", str(jp), "--description", "Promoted by PPC Lab guided exploration",
               "--tag", "exploration", "--tag", "novel"]
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout + 10.0, check=False)
        if p.returncode != 0:
            raise ExploreError(f"corpus promotion failed for {case_id}: {p.stderr.strip() or p.stdout.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ppc-lab")
    ap.add_argument("--worker")
    ap.add_argument("--corpus-tool")
    ap.add_argument("--root", type=Path, help="restrict target inputs to this root (default: manifest directory)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--promote-corpus", type=Path)
    ns = ap.parse_args()
    try:
        if ns.timeout <= 0:
            raise ExploreError("--timeout must be greater than zero")
        manifest_path = ns.manifest.expanduser().resolve(strict=True)
        base_dir = manifest_path.parent
        root = (ns.root.expanduser().resolve(strict=True) if ns.root else base_dir.resolve())
        if not root.is_dir():
            raise ExploreError("--root must be a directory")
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
            raise ExploreError(f"manifest schema must be {MANIFEST_SCHEMA}")
        base_job = manifest.get("base_job")
        if not isinstance(base_job, dict) or base_job.get("schema") != "ppc-lab-job-v1":
            raise ExploreError("base_job must be a ppc-lab-job-v1 object")
        axes_raw = manifest.get("axes")
        if not isinstance(axes_raw, list) or not axes_raw:
            raise ExploreError("axes must be a non-empty array")
        axes = [validate_axis(axis, i) for i, axis in enumerate(axes_raw)]
        paths = [x[0] for x in axes]
        if len(set(paths)) != len(paths):
            raise ExploreError("axis paths must be unique")
        strategy = manifest.get("strategy", "guided")
        if strategy not in ("guided", "cartesian", "adaptive"):
            raise ExploreError("strategy must be guided, adaptive, or cartesian")
        adaptive_cfg = manifest.get("adaptive", {})
        if adaptive_cfg is None:
            adaptive_cfg = {}
        if not isinstance(adaptive_cfg, dict):
            raise ExploreError("adaptive must be an object")
        plateau_window = int(adaptive_cfg.get("plateau_window", 8))
        plateau_rate = float(adaptive_cfg.get("plateau_novelty_rate", 0.125))
        min_cases = int(adaptive_cfg.get("min_cases", max(8, plateau_window)))
        if plateau_window < 1 or min_cases < 1 or not 0.0 <= plateau_rate <= 1.0:
            raise ExploreError("adaptive plateau_window/min_cases must be positive and novelty rate must be in 0..1")
        max_cases = manifest.get("max_cases", 64)
        if isinstance(max_cases, bool) or not isinstance(max_cases, int) or not 1 <= max_cases <= 100000:
            raise ExploreError("max_cases must be an integer in 1..100000")
        inputs = resolve_inputs(base_job, base_dir, root)
        cli = find_tool(ns.ppc_lab, "ppc-lab")
        worker = find_tool(ns.worker, "ppc-lab-worker")
        corpus_tool = find_tool(ns.corpus_tool, "ppc-lab-corpus") if ns.promote_corpus else None
        out = ns.out.expanduser().resolve()
        if out == root or root in out.parents:
            # Results may live outside the input root; living under it is safe too, but never let it replace the root itself.
            if out == root:
                raise ExploreError("--out cannot be the exploration input root itself")
        out.mkdir(parents=True, exist_ok=True)
        (out / "cases").mkdir(exist_ok=True)

        baseline: dict[str, Any] = {}
        for path, values in axes:
            first, second = path.split(".", 1)
            current = base_job.get(first, {})
            if isinstance(current, dict) and second in current:
                baseline[path] = copy.deepcopy(current[second])
            else:
                baseline[path] = copy.deepcopy(values[0])

        evaluated: set[str] = set()
        accepted_assignments: list[dict[str, Any]] = []
        seen_pcs: set[str] = set()
        seen_behaviors: set[str] = set()
        case_rows: list[dict[str, Any]] = []
        promoted = 0
        axis_stats: dict[str, dict[str, int]] = {path: {"attempts": 0, "novel": 0, "new_pcs": 0} for path in paths}
        stopped_early = False
        stop_reason: str | None = None

        def evaluate(assignment: dict[str, Any], parent: int | None, mutated_axis: str | None = None) -> tuple[bool, int]:
            nonlocal promoted
            key = assignment_key(assignment)
            if key in evaluated:
                return False, -1
            evaluated.add(key)
            job = job_with_assignment(base_job, assignment)
            response = run_worker(job, cli=cli, worker=worker, base_dir=base_dir, root=root, timeout=ns.timeout)
            pcs = trace_pcs(str(response.get("stderr", "")))
            pc_set = set(pcs)
            new_pcs = sorted(pc_set - seen_pcs)
            architecture = stable_architecture(response, assignment)
            behavior = canonical_hash(architecture)
            behavior_novel = behavior not in seen_behaviors
            novel = bool(new_pcs) or behavior_novel or not case_rows
            index = len(case_rows)
            row = {
                "schema": CASE_SCHEMA,
                "index": index,
                "parent": parent,
                "assignment": copy.deepcopy(assignment),
                "novel": novel,
                "novelty": {"new_pcs": new_pcs, "new_pc_count": len(new_pcs), "behavior_novel": behavior_novel},
                "behavior_sha256": behavior,
                "trace": {"events": len(pcs), "unique_pcs": len(pc_set), "pcs": sorted(pc_set)},
                "worker": response,
                "job": job,
            }
            write_json(out / "cases" / f"{index:05d}.json", row)
            case_rows.append(row)
            if mutated_axis in axis_stats:
                axis_stats[mutated_axis]["attempts"] += 1
                axis_stats[mutated_axis]["novel"] += int(novel)
                axis_stats[mutated_axis]["new_pcs"] += len(new_pcs)
            if novel:
                seen_pcs.update(pc_set)
                seen_behaviors.add(behavior)
                accepted_assignments.append(copy.deepcopy(assignment))
                if ns.promote_corpus and response.get("ok"):
                    cid = f"explore-{index:05d}-{behavior[:12]}"
                    promote(ns.promote_corpus.resolve(), cid, job, cli=cli, worker=worker, corpus_tool=corpus_tool,
                            base_dir=base_dir, root=root, timeout=ns.timeout)
                    row["promoted_case"] = cid
                    write_json(out / "cases" / f"{index:05d}.json", row)
                    promoted += 1
            return novel, index

        if strategy == "cartesian":
            for values in itertools.product(*(vals for _, vals in axes)):
                if len(case_rows) >= max_cases:
                    break
                assignment = dict(zip(paths, values))
                evaluate(assignment, None)
        elif strategy == "guided":
            queue: deque[tuple[dict[str, Any], int | None, str | None]] = deque([(baseline, None, None)])
            queued = {assignment_key(baseline)}
            while queue and len(case_rows) < max_cases:
                assignment, parent, mutated_axis = queue.popleft()
                novel, idx = evaluate(assignment, parent, mutated_axis)
                if not novel:
                    continue
                for path, values in axes:
                    for value in values:
                        if assignment.get(path) == value:
                            continue
                        child = copy.deepcopy(assignment)
                        child[path] = copy.deepcopy(value)
                        k = assignment_key(child)
                        if k in evaluated or k in queued:
                            continue
                        queued.add(k)
                        queue.append((child, idx, path))
        else:
            # Adaptive guided search: expand novel parents but choose the next mutation
            # from the axis with the best observed yield. Unknown axes retain an
            # exploration prior so they are sampled before PPC Lab overcommits to
            # an early winner. Candidate rescoring is deterministic at every pop.
            candidates: list[tuple[dict[str, Any], int | None, str | None, int]] = [(baseline, None, None, 0)]
            queued = {assignment_key(baseline)}
            serial = 1

            def axis_priority(path: str | None) -> float:
                if path is None:
                    return 1e9
                st = axis_stats[path]
                novelty_yield = (st["novel"] + 1.0) / (st["attempts"] + 2.0)
                coverage_yield = st["new_pcs"] / (st["attempts"] + 1.0)
                return novelty_yield + min(coverage_yield, 1000.0) * 0.01

            while candidates and len(case_rows) < max_cases:
                best_i = max(range(len(candidates)), key=lambda i: (axis_priority(candidates[i][2]), -candidates[i][3]))
                assignment, parent, mutated_axis, _ = candidates.pop(best_i)
                novel, idx = evaluate(assignment, parent, mutated_axis)

                if len(case_rows) >= min_cases and len(case_rows) >= plateau_window:
                    tail = case_rows[-plateau_window:]
                    tail_rate = sum(1 for row in tail if row["novel"]) / len(tail)
                    if tail_rate <= plateau_rate:
                        stopped_early = True
                        stop_reason = "novelty-plateau"
                        break

                if not novel:
                    continue
                for path, values in axes:
                    for value in values:
                        if assignment.get(path) == value:
                            continue
                        child = copy.deepcopy(assignment)
                        child[path] = copy.deepcopy(value)
                        k = assignment_key(child)
                        if k in evaluated or k in queued:
                            continue
                        queued.add(k)
                        candidates.append((child, idx, path, serial))
                        serial += 1

        summary = {
            "schema": SUMMARY_SCHEMA,
            "strategy": strategy,
            "manifest": str(manifest_path),
            "max_cases": max_cases,
            "evaluated_cases": len(case_rows),
            "novel_cases": sum(1 for row in case_rows if row["novel"]),
            "successful_cases": sum(1 for row in case_rows if row.get("worker", {}).get("ok")),
            "unique_pcs": len(seen_pcs),
            "unique_behaviors": len(seen_behaviors),
            "promoted_cases": promoted,
            "input_provenance": inputs,
            "cases": [
                {"index": row["index"], "parent": row["parent"], "novel": row["novel"],
                 "behavior_sha256": row["behavior_sha256"], "new_pc_count": row["novelty"]["new_pc_count"],
                 **({"promoted_case": row["promoted_case"]} if "promoted_case" in row else {})}
                for row in case_rows
            ],
            "axis_yield": {
                path: {
                    **stats,
                    "novelty_rate": round(stats["novel"] / stats["attempts"], 6) if stats["attempts"] else 0.0,
                    "new_pcs_per_case": round(stats["new_pcs"] / stats["attempts"], 6) if stats["attempts"] else 0.0,
                }
                for path, stats in sorted(axis_stats.items())
            },
        }
        if strategy == "adaptive":
            tail = case_rows[-min(plateau_window, len(case_rows)):]
            tail_rate = (sum(1 for row in tail if row["novel"]) / len(tail)) if tail else 0.0
            summary["adaptive"] = {
                "plateau_window": plateau_window,
                "plateau_novelty_rate": plateau_rate,
                "min_cases": min_cases,
                "stopped_early": stopped_early,
                "stop_reason": stop_reason,
                "tail_novelty_rate": round(tail_rate, 6),
                "unused_case_budget": max_cases - len(case_rows),
            }
        write_json(out / "summary.json", summary)
        print(f"evaluated={summary['evaluated_cases']} novel={summary['novel_cases']} unique_pcs={summary['unique_pcs']} promoted={promoted} out={out}")
        return 0
    except (ExploreError, json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
