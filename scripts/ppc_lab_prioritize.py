#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Rank PPC Lab exploration cases and quantify research yield deterministically."""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "ppc-lab-priority-report-v1"
DEFAULT_WEIGHTS = {
    "new_pc": 10.0,
    "behavior": 25.0,
    "failure": 40.0,
    "pc_rarity": 3.0,
}


class PriorityError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def load_cases(exploration: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary_path = exploration / "summary.json"
    cases_dir = exploration / "cases"
    if not summary_path.is_file() or not cases_dir.is_dir():
        raise PriorityError(f"not a PPC Lab exploration directory: {exploration}")
    summary = read_json(summary_path)
    if not isinstance(summary, dict) or summary.get("schema") != "ppc-lab-exploration-summary-v1":
        raise PriorityError("exploration summary schema mismatch")
    rows: list[dict[str, Any]] = []
    for path in sorted(cases_dir.glob("*.json")):
        row = read_json(path)
        if not isinstance(row, dict) or row.get("schema") != "ppc-lab-exploration-case-v1":
            raise PriorityError(f"case schema mismatch: {path}")
        rows.append(row)
    if not rows:
        raise PriorityError("exploration contains no cases")
    return summary, rows


def parse_weights(ns: argparse.Namespace) -> dict[str, float]:
    weights = {
        "new_pc": ns.weight_new_pc,
        "behavior": ns.weight_behavior,
        "failure": ns.weight_failure,
        "pc_rarity": ns.weight_pc_rarity,
    }
    if any(not math.isfinite(v) or v < 0 for v in weights.values()):
        raise PriorityError("priority weights must be finite and non-negative")
    return weights


def pc_frequency(rows: list[dict[str, Any]]) -> collections.Counter[str]:
    freq: collections.Counter[str] = collections.Counter()
    for row in rows:
        trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
        for pc in set(trace.get("pcs", []) if isinstance(trace.get("pcs"), list) else []):
            if isinstance(pc, str):
                freq[pc.lower()] += 1
    return freq


def analyze_axes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        assignment = row.get("assignment") if isinstance(row.get("assignment"), dict) else {}
        novel = bool(row.get("novel"))
        novelty = row.get("novelty") if isinstance(row.get("novelty"), dict) else {}
        new_pc_count = int(novelty.get("new_pc_count", 0) or 0)
        worker = row.get("worker") if isinstance(row.get("worker"), dict) else {}
        failed = not bool(worker.get("ok"))
        for path, value in assignment.items():
            key = canonical(value)
            slot = data.setdefault(path, {}).setdefault(key, {
                "value": value, "cases": 0, "novel_cases": 0, "new_pcs": 0, "failures": 0,
            })
            slot["cases"] += 1
            slot["novel_cases"] += int(novel)
            slot["new_pcs"] += new_pc_count
            slot["failures"] += int(failed)
    result = []
    for path, values in sorted(data.items()):
        rows_out = []
        total_cases = total_novel = total_new = total_fail = 0
        for _, slot in sorted(values.items()):
            cases = slot["cases"]
            row = {
                **slot,
                "novelty_rate": round(slot["novel_cases"] / cases, 6) if cases else 0.0,
                "new_pcs_per_case": round(slot["new_pcs"] / cases, 6) if cases else 0.0,
                "failure_rate": round(slot["failures"] / cases, 6) if cases else 0.0,
            }
            rows_out.append(row)
            total_cases += cases
            total_novel += slot["novel_cases"]
            total_new += slot["new_pcs"]
            total_fail += slot["failures"]
        result.append({
            "path": path,
            "cases": total_cases,
            "novel_cases": total_novel,
            "new_pcs": total_new,
            "failures": total_fail,
            "novelty_rate": round(total_novel / total_cases, 6) if total_cases else 0.0,
            "new_pcs_per_case": round(total_new / total_cases, 6) if total_cases else 0.0,
            "values": rows_out,
        })
    result.sort(key=lambda x: (-x["novelty_rate"], -x["new_pcs_per_case"], x["path"]))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("exploration", type=Path, help="exploration output directory")
    ap.add_argument("--json", type=Path, help="write ppc-lab-priority-report-v1 JSON")
    ap.add_argument("--top", type=int, default=16, help="number of recommended cases (default: 16)")
    ap.add_argument("--plateau-window", type=int, default=8)
    ap.add_argument("--plateau-novelty-rate", type=float, default=0.125)
    ap.add_argument("--weight-new-pc", type=float, default=DEFAULT_WEIGHTS["new_pc"])
    ap.add_argument("--weight-behavior", type=float, default=DEFAULT_WEIGHTS["behavior"])
    ap.add_argument("--weight-failure", type=float, default=DEFAULT_WEIGHTS["failure"])
    ap.add_argument("--weight-pc-rarity", type=float, default=DEFAULT_WEIGHTS["pc_rarity"])
    ns = ap.parse_args()
    try:
        if ns.top < 0 or ns.plateau_window < 1 or not 0.0 <= ns.plateau_novelty_rate <= 1.0:
            raise PriorityError("--top must be >=0, plateau window >=1, and plateau novelty rate in 0..1")
        weights = parse_weights(ns)
        exploration = ns.exploration.expanduser().resolve(strict=True)
        summary, rows = load_cases(exploration)
        freq = pc_frequency(rows)
        ranking = []
        for row in rows:
            novelty = row.get("novelty") if isinstance(row.get("novelty"), dict) else {}
            trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
            worker = row.get("worker") if isinstance(row.get("worker"), dict) else {}
            new_pc_count = int(novelty.get("new_pc_count", 0) or 0)
            behavior_novel = bool(novelty.get("behavior_novel"))
            failed = not bool(worker.get("ok"))
            pcs = set(pc.lower() for pc in trace.get("pcs", []) if isinstance(pc, str)) if isinstance(trace.get("pcs"), list) else set()
            rarity = sum(1.0 / max(1, freq[pc]) for pc in pcs)
            components = {
                "new_pc": new_pc_count * weights["new_pc"],
                "behavior": float(behavior_novel) * weights["behavior"],
                "failure": float(failed) * weights["failure"],
                "pc_rarity": rarity * weights["pc_rarity"],
            }
            score = sum(components.values())
            ranking.append({
                "index": int(row.get("index", len(ranking))),
                "score": round(score, 6),
                "components": {k: round(v, 6) for k, v in components.items()},
                "novel": bool(row.get("novel")),
                "failed": failed,
                "new_pc_count": new_pc_count,
                "behavior_sha256": row.get("behavior_sha256"),
                "parent": row.get("parent"),
            })
        ranking.sort(key=lambda x: (-x["score"], x["index"]))

        tail = rows[-min(ns.plateau_window, len(rows)):]
        tail_novel = sum(1 for row in tail if row.get("novel"))
        tail_new = sum(int((row.get("novelty") or {}).get("new_pc_count", 0) or 0) for row in tail)
        novelty_rate = tail_novel / len(tail) if tail else 0.0
        plateau = len(rows) >= ns.plateau_window and novelty_rate <= ns.plateau_novelty_rate
        report = {
            "schema": REPORT_SCHEMA,
            "exploration": str(exploration),
            "strategy": summary.get("strategy"),
            "evaluated_cases": len(rows),
            "weights": weights,
            "recommended_cases": [row["index"] for row in ranking[:ns.top]],
            "ranking": ranking,
            "axes": analyze_axes(rows),
            "plateau": {
                "window": ns.plateau_window,
                "threshold": ns.plateau_novelty_rate,
                "observed_cases": len(tail),
                "novel_cases": tail_novel,
                "new_pcs": tail_new,
                "novelty_rate": round(novelty_rate, 6),
                "saturated": plateau,
            },
        }
        if ns.json:
            write_json(ns.json.expanduser().resolve(), report)
        print(f"cases={len(rows)} top={len(report['recommended_cases'])} plateau={'yes' if plateau else 'no'}")
        for rank, row in enumerate(ranking[:ns.top], 1):
            print(f"{rank:02d} case={row['index']:05d} score={row['score']:.3f} new_pcs={row['new_pc_count']} failed={'yes' if row['failed'] else 'no'}")
        return 0
    except (PriorityError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ppc-lab-prioritize: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
