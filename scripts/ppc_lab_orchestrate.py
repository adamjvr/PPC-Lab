#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab parallel orchestration and deterministic result cache.

This is a dependency-free scheduler above ppc-lab-worker. It deliberately uses
ppc-lab-job-v1 as the execution contract rather than constructing ppc-lab CLI
arguments itself. The result is suitable for a build server, SSH login host,
container worker, CI runner, or local workstation without introducing a daemon.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ppc-lab-orchestration-v1"
JOB_RESULT_SCHEMA = "ppc-lab-orchestration-job-result-v1"
SUMMARY_SCHEMA = "ppc-lab-orchestration-summary-v1"
WORKER_RESPONSE_SCHEMA = "ppc-lab-worker-response-v1"


class ManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobSpec:
    index: int
    name: str
    job: dict[str, Any]
    base_dir: Path
    source: str


def _safe_name(value: str) -> str:
    text = "".join(c if c.isalnum() or c in "-_." else "_" for c in value).strip("._")
    return text[:120] or "job"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_existing_file(value: Any, base_dir: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{field} must be a non-empty path string")
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ManifestError(f"{field} does not exist: {path}") from exc
    if not path.is_file():
        raise ManifestError(f"{field} is not a file: {path}")
    return path


def _load_manifest(path: Path) -> tuple[dict[str, Any], list[JobSpec]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ManifestError(f"manifest schema must be {MANIFEST_SCHEMA}")
    raw_jobs = manifest.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ManifestError("manifest.jobs must be a non-empty array")
    if "parallelism" in manifest and (not isinstance(manifest["parallelism"], int) or isinstance(manifest["parallelism"], bool) or manifest["parallelism"] < 1):
        raise ManifestError("manifest.parallelism must be a positive integer")

    jobs: list[JobSpec] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw_jobs):
        if not isinstance(item, dict):
            raise ManifestError(f"jobs[{index}] must be an object")
        allowed = {"name", "job", "path"}
        extra = set(item) - allowed
        if extra:
            raise ManifestError(f"jobs[{index}] has unknown fields: {', '.join(sorted(extra))}")
        if ("job" in item) == ("path" in item):
            raise ManifestError(f"jobs[{index}] must contain exactly one of job or path")
        explicit_name = item.get("name")
        if explicit_name is not None and (not isinstance(explicit_name, str) or not explicit_name):
            raise ManifestError(f"jobs[{index}].name must be a non-empty string")

        if "path" in item:
            job_path = _resolve_existing_file(item["path"], path.parent, f"jobs[{index}].path")
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ManifestError(f"cannot read job {job_path}: {exc}") from exc
            base_dir = job_path.parent
            source = str(job_path)
            default_name = job_path.stem
        else:
            job = item["job"]
            base_dir = path.parent
            source = "inline"
            default_name = str(job.get("id", f"job-{index:04d}")) if isinstance(job, dict) else f"job-{index:04d}"

        if not isinstance(job, dict):
            raise ManifestError(f"jobs[{index}] job must be a JSON object")
        if job.get("schema") != "ppc-lab-job-v1":
            raise ManifestError(f"jobs[{index}] schema must be ppc-lab-job-v1")
        name = explicit_name or default_name
        if name in seen_names:
            raise ManifestError(f"duplicate job name: {name}")
        seen_names.add(name)
        jobs.append(JobSpec(index=index, name=name, job=job, base_dir=base_dir, source=source))
    return manifest, jobs


def _input_fingerprints(spec: JobSpec, root: Path | None) -> dict[str, dict[str, Any]]:
    image = spec.job.get("image")
    if not isinstance(image, dict):
        raise ManifestError(f"job {spec.name}: image must be an object")
    values: list[tuple[str, Any]] = [("image.path", image.get("path"))]
    if image.get("data_path") is not None:
        values.append(("image.data_path", image.get("data_path")))
    result: dict[str, dict[str, Any]] = {}
    for field, value in values:
        path = _resolve_existing_file(value, spec.base_dir, f"job {spec.name} {field}")
        if root is not None:
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ManifestError(f"job {spec.name} {field} is outside orchestration root: {path}") from exc
        result[field] = {
            "logical_path": value,
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return result


def _engine_identity(ppc_lab: Path) -> dict[str, Any]:
    proc = subprocess.run([str(ppc_lab), "capabilities", "--json"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise ManifestError(f"cannot query ppc-lab capabilities: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        caps = json.loads(proc.stdout)
    except Exception as exc:
        raise ManifestError(f"invalid ppc-lab capabilities JSON: {exc}") from exc
    if not isinstance(caps, dict) or caps.get("schema") != "ppc-lab-capabilities-v1":
        raise ManifestError("ppc-lab returned an unsupported capabilities document")
    return caps


def _cache_key(spec: JobSpec, engine: dict[str, Any], fingerprints: dict[str, Any]) -> str:
    material = {
        "protocol": MANIFEST_SCHEMA,
        "job": spec.job,
        "engine": {
            "version": engine.get("version"),
            "guest": engine.get("guest"),
            "formats": engine.get("formats"),
            "backends": engine.get("backends"),
        },
        "inputs": fingerprints,
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _valid_record(path: Path, cache_key: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(value, dict) or value.get("schema") != JOB_RESULT_SCHEMA or value.get("cache_key") != cache_key:
        return None
    response = value.get("response")
    if not isinstance(response, dict) or response.get("schema") != WORKER_RESPONSE_SCHEMA:
        return None
    return value


def _run_worker(spec: JobSpec, *, worker: Path, ppc_lab: Path, root: Path | None,
                timeout: float, expose_command: bool) -> tuple[dict[str, Any], float]:
    command = [sys.executable, str(worker), "--ppc-lab", str(ppc_lab), "--base-dir", str(spec.base_dir), "--timeout", str(timeout)]
    if root is not None:
        command += ["--root", str(root)]
    if expose_command:
        command.append("--expose-command")
    command += ["run", "-"]
    started = time.monotonic()
    proc = subprocess.run(command, input=json.dumps(spec.job), text=True, capture_output=True, check=False)
    elapsed = time.monotonic() - started
    try:
        response = json.loads(proc.stdout)
    except Exception as exc:
        response = {
            "schema": WORKER_RESPONSE_SCHEMA,
            "id": spec.job.get("id"),
            "ok": False,
            "exit_code": None,
            "timed_out": False,
            "error": f"worker transport failure: {exc}",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    if proc.stderr and isinstance(response, dict) and "worker_stderr" not in response:
        response["worker_stderr"] = proc.stderr
    return response, elapsed


def _publish_evidence(store: Path, result_dir: Path) -> tuple[bool, str]:
    source = Path(__file__).with_name("ppc_lab_evidence.py")
    installed = Path(__file__).with_name("ppc-lab-evidence")
    if source.is_file():
        command = [sys.executable, str(source)]
    elif installed.is_file():
        command = [str(installed)]
    else:
        tool = shutil.which("ppc-lab-evidence")
        if not tool:
            return False, "cannot find ppc-lab-evidence"
        command = [tool]
    proc = subprocess.run(command + ["ingest", str(store), str(result_dir), "--strict"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
    return True, proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel/resumable PPC Lab job orchestration")
    parser.add_argument("manifest", type=Path, help=f"{MANIFEST_SCHEMA} JSON file")
    parser.add_argument("--ppc-lab", help="path to ppc-lab (default: PPC_LAB_BIN or PATH)")
    parser.add_argument("--worker", help="path to ppc-lab-worker (default: sibling script or PATH)")
    parser.add_argument("--out", type=Path, required=True, help="result directory")
    parser.add_argument("--cache", type=Path, help="shared deterministic response cache")
    parser.add_argument("--parallel", type=int, help="parallel jobs (default: manifest.parallelism or CPU count)")
    parser.add_argument("--timeout", type=float, default=60.0, help="worker timeout per job in seconds")
    parser.add_argument("--root", type=Path, help="restrict all job input files to this directory tree")
    parser.add_argument("--resume", action="store_true", help="reuse matching completed records already in --out")
    parser.add_argument("--no-cache-read", action="store_true", help="do not reuse records from --cache")
    parser.add_argument("--no-cache-write", action="store_true", help="do not write successful records to --cache")
    parser.add_argument("--expose-command", action="store_true", help="retain worker command details for debugging")
    parser.add_argument("--evidence-store", type=Path, help="ingest the completed result directory into a PPC Lab evidence store")
    args = parser.parse_args()
    if args.parallel is not None and args.parallel < 1:
        parser.error("--parallel must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    manifest_path = args.manifest.expanduser().resolve()
    out = args.out.expanduser().resolve()
    cache = args.cache.expanduser().resolve() if args.cache else None
    root = args.root.expanduser().resolve() if args.root else None
    if root is not None and not root.is_dir():
        parser.error("--root must be an existing directory")

    ppc_lab_text = args.ppc_lab or os.environ.get("PPC_LAB_BIN") or shutil.which("ppc-lab")
    if not ppc_lab_text:
        parser.error("cannot find ppc-lab; use --ppc-lab or PPC_LAB_BIN")
    ppc_lab = Path(ppc_lab_text).expanduser().resolve()
    if not ppc_lab.is_file():
        parser.error(f"ppc-lab not found: {ppc_lab}")

    if args.worker:
        worker = Path(args.worker).expanduser().resolve()
    else:
        sibling_source = Path(__file__).with_name("ppc_lab_worker.py")
        sibling_installed = Path(__file__).with_name("ppc-lab-worker")
        worker_text = (str(sibling_source) if sibling_source.is_file() else
                       str(sibling_installed) if sibling_installed.is_file() else
                       shutil.which("ppc-lab-worker"))
        if not worker_text:
            parser.error("cannot find ppc-lab-worker; use --worker")
        worker = Path(worker_text).expanduser().resolve()
    if not worker.is_file():
        parser.error(f"worker not found: {worker}")

    try:
        manifest, jobs = _load_manifest(manifest_path)
        engine = _engine_identity(ppc_lab)
        prepared: list[tuple[JobSpec, dict[str, Any], str]] = []
        for spec in jobs:
            fingerprints = _input_fingerprints(spec, root)
            prepared.append((spec, fingerprints, _cache_key(spec, engine, fingerprints)))
    except ManifestError as exc:
        print(f"ppc-lab-orchestrate: {exc}", file=sys.stderr)
        return 2

    parallel = args.parallel or manifest.get("parallelism") or max(1, min(len(jobs), os.cpu_count() or 1))
    out.mkdir(parents=True, exist_ok=True)
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    records: dict[int, dict[str, Any]] = {}
    pending: list[tuple[JobSpec, dict[str, Any], str, Path]] = []
    resumed = cache_hits = 0
    for spec, fingerprints, key in prepared:
        result_path = out / f"{spec.index:04d}-{_safe_name(spec.name)}.json"
        if args.resume:
            record = _valid_record(result_path, key)
            if record is not None:
                record["reuse"] = "resume"
                records[spec.index] = record
                resumed += 1
                continue
        if cache is not None and not args.no_cache_read:
            cache_path = cache / key[:2] / f"{key}.json"
            record = _valid_record(cache_path, key)
            if record is not None:
                record = dict(record)
                record["reuse"] = "cache"
                _atomic_json(result_path, record)
                records[spec.index] = record
                cache_hits += 1
                continue
        pending.append((spec, fingerprints, key, result_path))

    def execute(item: tuple[JobSpec, dict[str, Any], str, Path]) -> tuple[int, dict[str, Any]]:
        spec, fingerprints, key, result_path = item
        response, elapsed = _run_worker(spec, worker=worker, ppc_lab=ppc_lab, root=root,
                                        timeout=args.timeout, expose_command=args.expose_command)
        record = {
            "schema": JOB_RESULT_SCHEMA,
            "name": spec.name,
            "index": spec.index,
            "source": spec.source,
            "cache_key": key,
            "engine_version": engine.get("version"),
            "duration_seconds": round(elapsed, 6),
            "inputs": fingerprints,
            "reuse": "executed",
            "response": response,
        }
        _atomic_json(result_path, record)
        if cache is not None and not args.no_cache_write and response.get("ok") is True:
            cache_path = cache / key[:2] / f"{key}.json"
            _atomic_json(cache_path, record)
        return spec.index, record

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="ppclab") as pool:
        futures = [pool.submit(execute, item) for item in pending]
        for future in concurrent.futures.as_completed(futures):
            index, record = future.result()
            records[index] = record
    duration = time.monotonic() - started

    ordered = [records[i] for i in range(len(jobs))]
    failures = sum(1 for record in ordered if record.get("response", {}).get("ok") is not True)
    executed = sum(1 for record in ordered if record.get("reuse") == "executed")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "manifest_schema": MANIFEST_SCHEMA,
        "manifest": str(manifest_path),
        "id": manifest.get("id"),
        "engine": engine,
        "parallelism": parallel,
        "jobs": len(ordered),
        "executed": executed,
        "resumed": resumed,
        "cache_hits": cache_hits,
        "failed": failures,
        "duration_seconds": round(duration, 6),
        "results": [
            {
                "index": record["index"],
                "name": record["name"],
                "cache_key": record["cache_key"],
                "reuse": record.get("reuse"),
                "ok": record.get("response", {}).get("ok") is True,
                "exit_code": record.get("response", {}).get("exit_code"),
                "file": f"{record['index']:04d}-{_safe_name(record['name'])}.json",
            }
            for record in ordered
        ],
    }
    if args.evidence_store is not None:
        summary["evidence_store"] = str(args.evidence_store.expanduser().resolve())
    _atomic_json(out / "summary.json", summary)
    if args.evidence_store is not None:
        ok, detail = _publish_evidence(args.evidence_store.expanduser().resolve(), out)
        if not ok:
            print(f"ppc-lab-orchestrate: evidence ingestion failed: {detail}", file=sys.stderr)
            return 2
    print(f"jobs={len(ordered)} executed={executed} resumed={resumed} cache_hits={cache_hits} failed={failures} summary={out/'summary.json'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
