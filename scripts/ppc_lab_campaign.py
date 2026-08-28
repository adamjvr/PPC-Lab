#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run a bounded PPC Lab research campaign end-to-end.

A campaign composes stable PPC Lab protocols/tools instead of introducing a
second execution engine. It can run guided exploration, promote novel cases to
a behavioral corpus, replay/verify that corpus, triage selected discoveries
across two engines/backends, and publish all generated JSON evidence into the
content-addressed evidence store.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CAMPAIGN_SCHEMA = "ppc-lab-campaign-v1"
STATE_SCHEMA = "ppc-lab-campaign-state-v1"
SUMMARY_SCHEMA = "ppc-lab-campaign-summary-v1"


class CampaignError(RuntimeError):
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


def contained(path: Path, root: Path) -> Path:
    p = path.expanduser().resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError as exc:
        raise CampaignError(f"path outside campaign root: {p}") from exc
    return p


def resolve_tool(value: str | None, default: str) -> Path:
    candidate = value or shutil.which(default)
    if not candidate:
        raise CampaignError(f"cannot find {default}; use the explicit tool option")
    p = Path(candidate).expanduser().resolve()
    if not p.is_file():
        raise CampaignError(f"tool is not a file: {p}")
    return p


def tool_command(path: Path, *args: str) -> list[str]:
    if path.suffix == ".py":
        return [sys.executable, str(path), *args]
    return [str(path), *args]


def engine_version(cli: Path) -> str:
    p = subprocess.run([str(cli), "--version"], text=True, capture_output=True, check=False)
    if p.returncode:
        raise CampaignError(p.stderr.strip() or "cannot query PPC Lab version")
    text = p.stdout.strip()
    return text.removeprefix("PPC Lab ").strip()


def capabilities(cli: Path) -> dict[str, Any]:
    p = subprocess.run([str(cli), "capabilities", "--json"], text=True, capture_output=True, check=False)
    if p.returncode:
        raise CampaignError(p.stderr.strip() or "cannot query PPC Lab capabilities")
    try:
        value = json.loads(p.stdout)
    except Exception as exc:
        raise CampaignError("PPC Lab capabilities returned invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != "ppc-lab-capabilities-v1":
        raise CampaignError("unexpected PPC Lab capability schema")
    return value


def absolute_job_inputs(job: dict[str, Any], base_dir: Path, root: Path) -> dict[str, Any]:
    out = copy.deepcopy(job)
    image = out.get("image")
    if not isinstance(image, dict):
        raise CampaignError("exploration.base_job.image must be an object")
    for field in ("path", "data_path"):
        raw = image.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw:
            raise CampaignError(f"image.{field} must be a non-empty string")
        p = Path(raw)
        if not p.is_absolute():
            p = base_dir / p
        resolved = contained(p, root)
        if not resolved.is_file():
            raise CampaignError(f"image.{field} missing: {resolved}")
        image[field] = str(resolved)
    return out


def resolve_external_path(raw: str | None, base_dir: Path, default: Path | None = None) -> Path | None:
    if raw is None:
        return default
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()


def run_checked(command: list[str], *, timeout: float, cwd: Path | None = None, ok_codes: set[int] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        p = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CampaignError(f"command timed out after {timeout:g}s: {' '.join(command)}") from exc
    allowed = ok_codes if ok_codes is not None else {0}
    if p.returncode not in allowed:
        detail = p.stderr.strip() or p.stdout.strip()
        raise CampaignError(f"command failed ({p.returncode}): {' '.join(command)}" + (f"\n{detail}" if detail else ""))
    return p


def stage_record(name: str, status: str, started: float, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "elapsed_seconds": round(time.monotonic() - started, 6), **extra}


def validate_campaign(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema") != CAMPAIGN_SCHEMA:
        raise CampaignError(f"campaign schema must be {CAMPAIGN_SCHEMA}")
    exploration = doc.get("exploration")
    if not isinstance(exploration, dict) or exploration.get("schema") != "ppc-lab-exploration-v1":
        raise CampaignError("exploration must be an inline ppc-lab-exploration-v1 object")
    name = doc.get("name", "campaign")
    if not isinstance(name, str) or not name.strip():
        raise CampaignError("name must be a non-empty string")
    return doc


def load_or_create_state(out: Path, manifest_hash: str, version: str, resume: bool) -> dict[str, Any]:
    path = out / "state.json"
    if path.exists():
        if not resume:
            raise CampaignError(f"campaign output already contains state; use --resume or choose another --out: {out}")
        state = read_json(path)
        if state.get("schema") != STATE_SCHEMA:
            raise CampaignError("campaign state schema mismatch")
        if state.get("manifest_sha256") != manifest_hash:
            raise CampaignError("campaign manifest changed since checkpoint; start a new output directory")
        if state.get("engine_version") != version:
            raise CampaignError(f"campaign engine changed from {state.get('engine_version')} to {version}; start a new output directory")
        return state
    if resume:
        raise CampaignError("--resume requested but campaign state does not exist")
    state = {
        "schema": STATE_SCHEMA,
        "manifest_sha256": manifest_hash,
        "engine_version": version,
        "completed": [],
        "stages": {},
    }
    write_json(path, state)
    return state


def save_state(out: Path, state: dict[str, Any]) -> None:
    write_json(out / "state.json", state)


def complete_stage(out: Path, state: dict[str, Any], name: str, record: dict[str, Any]) -> None:
    if name not in state["completed"]:
        state["completed"].append(name)
    state["stages"][name] = record
    save_state(out, state)


def campaign_timeout(deadline: float | None, fallback: float) -> float:
    if deadline is None:
        return fallback
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CampaignError("campaign wall-clock budget exhausted")
    return max(0.1, min(fallback, remaining))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, help="target-input containment root (default: manifest directory)")
    ap.add_argument("--ppc-lab")
    ap.add_argument("--worker")
    ap.add_argument("--explorer")
    ap.add_argument("--corpus-tool")
    ap.add_argument("--triage-tool")
    ap.add_argument("--evidence-tool")
    ap.add_argument("--right-ppc-lab", help="optional second PPC Lab executable for differential triage")
    ap.add_argument("--right-worker", help="optional second worker executable for differential triage")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args()

    try:
        manifest_path = ns.manifest.expanduser().resolve(strict=True)
        base_dir = manifest_path.parent
        root = ns.root.expanduser().resolve(strict=True) if ns.root else base_dir.resolve()
        if not root.is_dir():
            raise CampaignError("--root must be a directory")
        manifest = validate_campaign(read_json(manifest_path))
        out = ns.out.expanduser().resolve()
        if out == root:
            raise CampaignError("--out cannot replace the campaign input root")
        out.mkdir(parents=True, exist_ok=True)

        cli = resolve_tool(ns.ppc_lab, "ppc-lab")
        worker = resolve_tool(ns.worker, "ppc-lab-worker")
        explorer = resolve_tool(ns.explorer, "ppc-lab-explore")
        corpus_tool = resolve_tool(ns.corpus_tool, "ppc-lab-corpus")
        triage_tool = resolve_tool(ns.triage_tool, "ppc-lab-triage")
        evidence_tool = resolve_tool(ns.evidence_tool, "ppc-lab-evidence")
        right_cli = resolve_tool(ns.right_ppc_lab, "ppc-lab") if ns.right_ppc_lab else cli
        right_worker = resolve_tool(ns.right_worker, "ppc-lab-worker") if ns.right_worker else worker

        version = engine_version(cli)
        caps = capabilities(cli)
        manifest_hash = sha256_file(manifest_path)
        budget = manifest.get("budgets", {})
        if not isinstance(budget, dict):
            raise CampaignError("budgets must be an object")
        case_timeout = float(budget.get("case_timeout_seconds", 30.0))
        wall = budget.get("wall_seconds")
        wall_seconds = None if wall is None else float(wall)
        max_triage = int(budget.get("max_triage_cases", 8))
        if case_timeout <= 0 or (wall_seconds is not None and wall_seconds <= 0) or max_triage < 0:
            raise CampaignError("campaign budgets must be positive (max_triage_cases may be zero)")
        deadline = None if wall_seconds is None else time.monotonic() + wall_seconds

        # Preflight resolves and validates target inputs before any output-producing stage.
        exploration = copy.deepcopy(manifest["exploration"])
        exploration["base_job"] = absolute_job_inputs(exploration.get("base_job", {}), base_dir, root)
        if "max_cases" in budget:
            configured = int(budget["max_cases"])
            if configured < 1:
                raise CampaignError("budgets.max_cases must be at least 1")
            exploration["max_cases"] = min(int(exploration.get("max_cases", configured)), configured)

        corpus_cfg = manifest.get("corpus", {})
        if corpus_cfg is None:
            corpus_cfg = {}
        if not isinstance(corpus_cfg, dict):
            raise CampaignError("corpus must be an object")
        corpus_path = resolve_external_path(corpus_cfg.get("path"), base_dir, out / "corpus")
        promote = bool(corpus_cfg.get("promote_novel", True))
        replay = bool(corpus_cfg.get("replay", True))
        verify_corpus = bool(corpus_cfg.get("verify", True))

        triage_cfg = manifest.get("triage", {})
        if triage_cfg is None:
            triage_cfg = {}
        if not isinstance(triage_cfg, dict):
            raise CampaignError("triage must be an object")
        triage_enabled = bool(triage_cfg.get("enabled", True)) and max_triage > 0
        triage_select = triage_cfg.get("select", "novel-or-failed")
        if triage_select not in ("novel", "failed", "novel-or-failed", "all"):
            raise CampaignError("triage.select must be novel, failed, novel-or-failed, or all")
        left_backend = str(triage_cfg.get("left_backend", "builtin"))
        right_backend = str(triage_cfg.get("right_backend", "auto"))
        if left_backend not in ("auto", "builtin", "unicorn") or right_backend not in ("auto", "builtin", "unicorn"):
            raise CampaignError("triage backends must be auto, builtin, or unicorn")

        evidence_cfg = manifest.get("evidence", {})
        if evidence_cfg is None:
            evidence_cfg = {}
        if not isinstance(evidence_cfg, dict):
            raise CampaignError("evidence must be an object")
        evidence_enabled = bool(evidence_cfg.get("publish", True))
        evidence_path = resolve_external_path(evidence_cfg.get("store"), base_dir, out / "evidence")
        evidence_verify = bool(evidence_cfg.get("verify", True))

        plan = {
            "schema": SUMMARY_SCHEMA,
            "status": "dry-run" if ns.dry_run else "planned",
            "name": manifest.get("name", "campaign"),
            "engine_version": version,
            "manifest_sha256": manifest_hash,
            "root": str(root),
            "out": str(out),
            "capabilities": caps,
            "plan": {
                "exploration_max_cases": exploration.get("max_cases", 64),
                "promote_novel": promote,
                "corpus": str(corpus_path),
                "corpus_replay": replay,
                "triage": triage_enabled,
                "triage_select": triage_select,
                "max_triage_cases": max_triage,
                "triage_backends": [left_backend, right_backend],
                "evidence": evidence_enabled,
                "evidence_store": str(evidence_path),
            },
        }
        if ns.dry_run:
            write_json(out / "summary.json", plan)
            print(json.dumps(plan["plan"], sort_keys=True))
            return 0

        state = load_or_create_state(out, manifest_hash, version, ns.resume)
        generated = out / "campaign.exploration.json"
        write_json(generated, exploration)

        # Stage 1: guided exploration + successful novel-case promotion.
        explore_out = out / "exploration"
        if "exploration" not in state["completed"]:
            started = time.monotonic()
            cmd = tool_command(explorer, str(generated), "--out", str(explore_out), "--ppc-lab", str(cli), "--worker", str(worker), "--corpus-tool", str(corpus_tool), "--root", str(root), "--timeout", str(case_timeout))
            if promote:
                cmd += ["--promote-corpus", str(corpus_path)]
            p = run_checked(cmd, timeout=campaign_timeout(deadline, max(30.0, case_timeout * (int(exploration.get("max_cases", 64)) + 2))))
            summary = read_json(explore_out / "summary.json")
            record = stage_record("exploration", "complete", started, stdout=p.stdout.strip(), summary=summary)
            complete_stage(out, state, "exploration", record)
        exploration_summary = read_json(explore_out / "summary.json")

        # Stage 2: corpus structural verification and replay of promoted cases.
        corpus_stage: dict[str, Any] = {"verified": False, "replayed": False, "cases": 0, "failed": 0}
        if "corpus" not in state["completed"]:
            started = time.monotonic()
            manifest_file = corpus_path / "manifest.json"
            if manifest_file.is_file():
                if verify_corpus:
                    p = run_checked(tool_command(corpus_tool, "--ppc-lab", str(cli), "--worker", str(worker), "--timeout", str(case_timeout), "verify", str(corpus_path)), timeout=campaign_timeout(deadline, max(15.0, case_timeout)))
                    corpus_stage["verified"] = True
                    corpus_stage["verify_stdout"] = p.stdout.strip()
                if replay:
                    replay_json = out / "corpus-replay.json"
                    p = run_checked(tool_command(corpus_tool, "--ppc-lab", str(cli), "--worker", str(worker), "--timeout", str(case_timeout), "replay", str(corpus_path), "--input-root", str(root), "--json", str(replay_json)), timeout=campaign_timeout(deadline, max(30.0, case_timeout * (int(exploration_summary.get("promoted_cases", 1)) + 2))), ok_codes={0, 1})
                    replay_doc = read_json(replay_json)
                    corpus_stage.update({"replayed": True, "cases": replay_doc.get("cases", 0), "failed": replay_doc.get("failed", 0), "replay_exit_code": p.returncode})
            else:
                corpus_stage["skipped"] = "no promoted corpus cases"
            complete_stage(out, state, "corpus", stage_record("corpus", "complete", started, **corpus_stage))
        else:
            corpus_stage.update(state["stages"]["corpus"])

        # Stage 3: differential triage selected discoveries.
        triage_rows: list[dict[str, Any]] = []
        triage_dir = out / "triage"
        if "triage" not in state["completed"]:
            started = time.monotonic()
            triage_dir.mkdir(parents=True, exist_ok=True)
            if triage_enabled:
                case_files = sorted((explore_out / "cases").glob("*.json"))
                selected: list[dict[str, Any]] = []
                for case_file in case_files:
                    row = read_json(case_file)
                    worker_response = row.get("worker") if isinstance(row.get("worker"), dict) else {}
                    novel = bool(row.get("novel"))
                    failed = not bool(worker_response.get("ok"))
                    take = triage_select == "all" or (triage_select == "novel" and novel) or (triage_select == "failed" and failed) or (triage_select == "novel-or-failed" and (novel or failed))
                    if take:
                        selected.append(row)
                    if len(selected) >= max_triage:
                        break
                for row in selected:
                    campaign_timeout(deadline, case_timeout)
                    idx = int(row.get("index", len(triage_rows)))
                    case_dir = triage_dir / f"{idx:05d}"
                    case_dir.mkdir(parents=True, exist_ok=True)
                    job = absolute_job_inputs(row.get("job", {}), base_dir, root)
                    job_path = case_dir / "job.json"
                    report_path = case_dir / "triage.json"
                    bundle_path = case_dir / "bundle"
                    write_json(job_path, job)
                    cmd = tool_command(
                        triage_tool, "run", str(job_path), "--left-ppc-lab", str(cli), "--right-ppc-lab", str(right_cli),
                        "--left-worker", str(worker), "--right-worker", str(right_worker), "--left-backend", left_backend,
                        "--right-backend", right_backend, "--root", str(root), "--timeout", str(case_timeout),
                        "--json", str(report_path), "--bundle", str(bundle_path),
                    )
                    p = run_checked(cmd, timeout=campaign_timeout(deadline, case_timeout + 10.0), ok_codes={0})
                    report = read_json(report_path)
                    triage_rows.append({
                        "index": idx,
                        "equal": bool(report.get("equal")),
                        "classification": report.get("classification"),
                        "report": str(report_path),
                        "bundle": str(bundle_path),
                        "stdout": p.stdout.strip(),
                    })
            write_json(triage_dir / "summary.json", {
                "schema": "ppc-lab-campaign-triage-summary-v1",
                "selected": len(triage_rows),
                "divergences": sum(1 for r in triage_rows if not r["equal"]),
                "results": triage_rows,
            })
            complete_stage(out, state, "triage", stage_record("triage", "complete", started, selected=len(triage_rows), divergences=sum(1 for r in triage_rows if not r["equal"])))
        else:
            ts = triage_dir / "summary.json"
            if ts.is_file():
                triage_rows = read_json(ts).get("results", [])

        # Stage 4: evidence publication after all prior JSON artifacts are final.
        evidence_result: dict[str, Any] = {"published": False}
        if "evidence" not in state["completed"]:
            started = time.monotonic()
            if evidence_enabled:
                sources = [str(explore_out), str(triage_dir)]
                replay_json = out / "corpus-replay.json"
                if replay_json.is_file():
                    sources.append(str(replay_json))
                if corpus_path.is_dir():
                    sources.append(str(corpus_path))
                cmd = tool_command(evidence_tool, "ingest", str(evidence_path), *sources, "--json")
                p = run_checked(cmd, timeout=campaign_timeout(deadline, 60.0))
                try:
                    evidence_result = json.loads(p.stdout)
                except Exception as exc:
                    raise CampaignError("evidence ingest returned invalid JSON") from exc
                evidence_result["published"] = True
                if evidence_verify:
                    vp = run_checked(tool_command(evidence_tool, "verify", str(evidence_path), "--json"), timeout=campaign_timeout(deadline, 60.0), ok_codes={0, 1})
                    verify_doc = json.loads(vp.stdout)
                    evidence_result["verify"] = verify_doc
                    if not verify_doc.get("ok"):
                        raise CampaignError("evidence store verification failed")
            complete_stage(out, state, "evidence", stage_record("evidence", "complete", started, **evidence_result))
        else:
            evidence_result.update(state["stages"]["evidence"])

        triage_summary_path = triage_dir / "summary.json"
        triage_summary = read_json(triage_summary_path) if triage_summary_path.is_file() else {"selected": 0, "divergences": 0, "results": []}
        replay_path = out / "corpus-replay.json"
        replay_doc = read_json(replay_path) if replay_path.is_file() else None
        status = "complete"
        findings: list[str] = []
        if int(triage_summary.get("divergences", 0)):
            findings.append("differential-divergence")
        if int(exploration_summary.get("successful_cases", 0)) < int(exploration_summary.get("evaluated_cases", 0)):
            findings.append("guest-failures")
        if replay_doc and int(replay_doc.get("failed", 0)):
            findings.append("corpus-regression")
            status = "complete-with-regressions"
        elif findings:
            status = "complete-with-findings"

        final = {
            "schema": SUMMARY_SCHEMA,
            "status": status,
            "name": manifest.get("name", "campaign"),
            "engine_version": version,
            "manifest": str(manifest_path),
            "manifest_sha256": manifest_hash,
            "root": str(root),
            "out": str(out),
            "findings": findings,
            "exploration": exploration_summary,
            "corpus": {
                "path": str(corpus_path),
                "promoted_cases": exploration_summary.get("promoted_cases", 0),
                "replay": replay_doc,
            },
            "triage": triage_summary,
            "evidence": {"store": str(evidence_path), **evidence_result},
            "stages": state["stages"],
        }
        write_json(out / "summary.json", final)
        print(f"status={status} evaluated={exploration_summary.get('evaluated_cases',0)} novel={exploration_summary.get('novel_cases',0)} promoted={exploration_summary.get('promoted_cases',0)} triaged={triage_summary.get('selected',0)} divergences={triage_summary.get('divergences',0)} out={out}")
        return 1 if status == "complete-with-regressions" else 0

    except (CampaignError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ppc-lab-campaign: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
