#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab distributed worker-fleet scheduler.

Dependency-free orchestration above ppc-lab-job-v1 / ppc-lab-worker-response-v1.
Hosts may be local processes or OpenSSH endpoints. Input binaries are staged by
SHA-256 content identity, jobs are bounded by per-host slot counts, and transient
transport failures may be retried on another compatible host.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

FLEET_SCHEMA = "ppc-lab-fleet-v1"
JOB_SCHEMA = "ppc-lab-job-v1"
WORKER_RESPONSE_SCHEMA = "ppc-lab-worker-response-v1"
JOB_RESULT_SCHEMA = "ppc-lab-fleet-job-result-v1"
SUMMARY_SCHEMA = "ppc-lab-fleet-summary-v1"
CAPABILITIES_SCHEMA = "ppc-lab-capabilities-v1"


class FleetError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobSpec:
    index: int
    name: str
    job: dict[str, Any]
    base_dir: Path
    source: str
    required_tags: frozenset[str] = frozenset()


@dataclass
class HostSpec:
    index: int
    name: str
    transport: str
    slots: int
    root: str
    ppc_lab: str
    worker: str
    endpoint: str | None = None
    python: str = "python3"
    tags: frozenset[str] = frozenset()
    capabilities: dict[str, Any] | None = None
    error: str | None = None
    semaphore: threading.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.semaphore = threading.Semaphore(self.slots)


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


def _resolve_existing_file(value: Any, base_dir: Path, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FleetError(f"{field_name} must be a non-empty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FleetError(f"{field_name} does not exist: {path}") from exc
    if not path.is_file():
        raise FleetError(f"{field_name} is not a file: {path}")
    return path


def _string_list(value: Any, field_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise FleetError(f"{field_name} must be an array of non-empty strings")
    return frozenset(value)


def _load_manifest(path: Path) -> tuple[dict[str, Any], list[HostSpec], list[JobSpec]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FleetError(f"cannot read fleet manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != FLEET_SCHEMA:
        raise FleetError(f"manifest schema must be {FLEET_SCHEMA}")

    raw_hosts = manifest.get("hosts")
    raw_jobs = manifest.get("jobs")
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise FleetError("manifest.hosts must be a non-empty array")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise FleetError("manifest.jobs must be a non-empty array")
    if "retries" in manifest and (not isinstance(manifest["retries"], int) or isinstance(manifest["retries"], bool) or manifest["retries"] < 0):
        raise FleetError("manifest.retries must be a non-negative integer")
    if "timeout" in manifest and (not isinstance(manifest["timeout"], (int, float)) or isinstance(manifest["timeout"], bool) or manifest["timeout"] <= 0):
        raise FleetError("manifest.timeout must be greater than zero")

    hosts: list[HostSpec] = []
    seen_hosts: set[str] = set()
    for index, item in enumerate(raw_hosts):
        if not isinstance(item, dict):
            raise FleetError(f"hosts[{index}] must be an object")
        allowed = {"name", "transport", "endpoint", "slots", "root", "ppc_lab", "worker", "python", "tags"}
        extra = set(item) - allowed
        if extra:
            raise FleetError(f"hosts[{index}] has unknown fields: {', '.join(sorted(extra))}")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise FleetError(f"hosts[{index}].name must be a non-empty string")
        if name in seen_hosts:
            raise FleetError(f"duplicate host name: {name}")
        seen_hosts.add(name)
        transport = item.get("transport", "ssh")
        if transport not in ("local", "ssh"):
            raise FleetError(f"hosts[{index}].transport must be local or ssh")
        endpoint = item.get("endpoint")
        if transport == "ssh" and (not isinstance(endpoint, str) or not endpoint):
            raise FleetError(f"hosts[{index}].endpoint is required for ssh transport")
        if endpoint is not None and not isinstance(endpoint, str):
            raise FleetError(f"hosts[{index}].endpoint must be a string")
        slots = item.get("slots", 1)
        if not isinstance(slots, int) or isinstance(slots, bool) or slots < 1:
            raise FleetError(f"hosts[{index}].slots must be a positive integer")
        root = item.get("root")
        if not isinstance(root, str) or not root:
            raise FleetError(f"hosts[{index}].root must be a non-empty path string")
        if transport == "local":
            root_path = Path(root).expanduser()
            if not root_path.is_absolute():
                root_path = path.parent / root_path
            root = str(root_path.resolve())
        elif not root.startswith("/"):
            raise FleetError(f"hosts[{index}].root must be an absolute POSIX path for ssh transport")
        ppc_lab = item.get("ppc_lab", "ppc-lab")
        worker = item.get("worker", "ppc-lab-worker")
        python = item.get("python", "python3")
        for field_name, value in (("ppc_lab", ppc_lab), ("worker", worker), ("python", python)):
            if not isinstance(value, str) or not value:
                raise FleetError(f"hosts[{index}].{field_name} must be a non-empty string")
        hosts.append(HostSpec(index=index, name=name, transport=transport, endpoint=endpoint,
                              slots=slots, root=root, ppc_lab=ppc_lab, worker=worker,
                              python=python, tags=_string_list(item.get("tags"), f"hosts[{index}].tags")))

    jobs: list[JobSpec] = []
    seen_jobs: set[str] = set()
    for index, item in enumerate(raw_jobs):
        if not isinstance(item, dict):
            raise FleetError(f"jobs[{index}] must be an object")
        allowed = {"name", "job", "path", "requires_tags"}
        extra = set(item) - allowed
        if extra:
            raise FleetError(f"jobs[{index}] has unknown fields: {', '.join(sorted(extra))}")
        if ("job" in item) == ("path" in item):
            raise FleetError(f"jobs[{index}] must contain exactly one of job or path")
        if "path" in item:
            job_path = _resolve_existing_file(item["path"], path.parent, f"jobs[{index}].path")
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise FleetError(f"cannot read job {job_path}: {exc}") from exc
            base_dir = job_path.parent
            source = str(job_path)
            default_name = job_path.stem
        else:
            job = item["job"]
            base_dir = path.parent
            source = "inline"
            default_name = str(job.get("id", f"job-{index:04d}")) if isinstance(job, dict) else f"job-{index:04d}"
        if not isinstance(job, dict) or job.get("schema") != JOB_SCHEMA:
            raise FleetError(f"jobs[{index}] schema must be {JOB_SCHEMA}")
        name = item.get("name", default_name)
        if not isinstance(name, str) or not name:
            raise FleetError(f"jobs[{index}].name must be a non-empty string")
        if name in seen_jobs:
            raise FleetError(f"duplicate job name: {name}")
        seen_jobs.add(name)
        jobs.append(JobSpec(index=index, name=name, job=job, base_dir=base_dir, source=source,
                            required_tags=_string_list(item.get("requires_tags"), f"jobs[{index}].requires_tags")))
    return manifest, hosts, jobs


def _job_inputs(spec: JobSpec, local_root: Path | None) -> dict[str, dict[str, Any]]:
    image = spec.job.get("image")
    if not isinstance(image, dict):
        raise FleetError(f"job {spec.name}: image must be an object")
    fields: list[tuple[str, Any]] = [("image.path", image.get("path"))]
    if image.get("data_path") is not None:
        fields.append(("image.data_path", image.get("data_path")))
    result: dict[str, dict[str, Any]] = {}
    for field_name, value in fields:
        path = _resolve_existing_file(value, spec.base_dir, f"job {spec.name} {field_name}")
        if local_root is not None:
            try:
                path.relative_to(local_root)
            except ValueError as exc:
                raise FleetError(f"job {spec.name} {field_name} is outside local root: {path}") from exc
        result[field_name] = {
            "path": path,
            "logical_path": value,
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return result


def _run(cmd: list[str], *, input_text: str | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)


def _ssh_cmd(ssh: str, ssh_options: list[str], host: HostSpec, remote_argv: list[str]) -> list[str]:
    assert host.endpoint is not None
    return [ssh, *ssh_options, host.endpoint, shlex.join(remote_argv)]


def _probe_host(host: HostSpec, *, ssh: str, ssh_options: list[str], probe_timeout: float) -> None:
    try:
        if host.transport == "local":
            root = Path(host.root).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            cmd = [host.ppc_lab, "capabilities", "--json"]
        else:
            cmd = _ssh_cmd(ssh, ssh_options, host, [host.ppc_lab, "capabilities", "--json"])
        proc = _run(cmd, timeout=probe_timeout)
        if proc.returncode != 0:
            raise FleetError(proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
        caps = json.loads(proc.stdout)
        if not isinstance(caps, dict) or caps.get("schema") != CAPABILITIES_SCHEMA:
            raise FleetError("unsupported capabilities document")
        protocols = caps.get("protocols")
        if not isinstance(protocols, dict) or protocols.get("job") != JOB_SCHEMA or protocols.get("worker_response") != WORKER_RESPONSE_SCHEMA:
            raise FleetError("host does not advertise the required worker protocols")
        if host.transport == "local":
            worker_path = Path(host.worker).expanduser()
            worker_ok = worker_path.is_file() if (worker_path.is_absolute() or "/" in host.worker) else shutil.which(host.worker) is not None
            if not worker_ok:
                raise FleetError(f"worker not found on local host: {host.worker}")
        else:
            # Remote Python is already required by ppc-lab-worker and is also used for portable hashing/staging.
            code = "import pathlib,shutil,sys; v=sys.argv[1]; p=pathlib.Path(v); sys.exit(0 if (p.is_file() if '/' in v else shutil.which(v) is not None) else 1)"
            check = _run(_ssh_cmd(ssh, ssh_options, host, [host.python, "-c", code, host.worker]), timeout=probe_timeout)
            if check.returncode != 0:
                raise FleetError(f"worker not found on remote host: {host.worker}")
        host.capabilities = caps
    except Exception as exc:
        host.error = str(exc)
        host.capabilities = None


def _remote_store_path(host: HostSpec, digest: str) -> str:
    return str(PurePosixPath(host.root) / ".ppc-lab" / "store" / digest)


def _stage_local(host: HostSpec, source: Path, digest: str) -> str:
    root = Path(host.root).expanduser().resolve()
    store = root / ".ppc-lab" / "store"
    store.mkdir(parents=True, exist_ok=True)
    dest = store / digest
    if dest.exists() and dest.is_file() and _sha256_file(dest) == digest:
        return str(dest)
    fd, temp_name = tempfile.mkstemp(prefix=digest + ".", suffix=".tmp", dir=store)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copyfile(source, temp)
        if _sha256_file(temp) != digest:
            raise FleetError(f"local staging hash mismatch for {source}")
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    return str(dest)


def _remote_hash_ok(host: HostSpec, remote: str, digest: str, *, ssh: str, ssh_options: list[str], timeout: float) -> bool:
    code = (
        "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); "
        "h=hashlib.sha256(); "
        "f=p.open('rb') if p.is_file() else None; "
        "[(h.update(c)) for c in iter(lambda: f.read(1048576), b'')] if f else None; "
        "f.close() if f else None; sys.exit(0 if f and h.hexdigest()==sys.argv[2] else 1)"
    )
    proc = _run(_ssh_cmd(ssh, ssh_options, host, [host.python, "-c", code, remote, digest]), timeout=timeout)
    return proc.returncode == 0


def _stage_ssh(host: HostSpec, source: Path, digest: str, *, ssh: str, scp: str,
               ssh_options: list[str], timeout: float) -> str:
    assert host.endpoint is not None
    remote = _remote_store_path(host, digest)
    if _remote_hash_ok(host, remote, digest, ssh=ssh, ssh_options=ssh_options, timeout=timeout):
        return remote
    parent = str(PurePosixPath(remote).parent)
    proc = _run(_ssh_cmd(ssh, ssh_options, host, [host.python, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir(parents=True,exist_ok=True)", parent]), timeout=timeout)
    if proc.returncode != 0:
        raise FleetError(f"{host.name}: cannot create remote store: {proc.stderr.strip()}")
    temp = remote + f".tmp.{os.getpid()}.{threading.get_ident()}"
    scp_opts: list[str] = []
    # Reuse -o options accepted by both ssh and scp; omit ssh-only destination semantics.
    for i, token in enumerate(ssh_options):
        if token == "-o" and i + 1 < len(ssh_options):
            scp_opts.extend([token, ssh_options[i + 1]])
    proc = _run([scp, *scp_opts, str(source), f"{host.endpoint}:{shlex.quote(temp)}"], timeout=timeout)
    if proc.returncode != 0:
        raise FleetError(f"{host.name}: scp failed: {proc.stderr.strip() or proc.stdout.strip()}")
    code = (
        "import hashlib,os,pathlib,sys; p=pathlib.Path(sys.argv[1]); h=hashlib.sha256(); "
        "f=p.open('rb'); [h.update(c) for c in iter(lambda:f.read(1048576),b'')]; f.close(); "
        "sys.exit(2) if h.hexdigest()!=sys.argv[3] else os.replace(sys.argv[1],sys.argv[2])"
    )
    proc = _run(_ssh_cmd(ssh, ssh_options, host, [host.python, "-c", code, temp, remote, digest]), timeout=timeout)
    if proc.returncode != 0:
        _run(_ssh_cmd(ssh, ssh_options, host, [host.python, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).unlink(missing_ok=True)", temp]), timeout=timeout)
        raise FleetError(f"{host.name}: remote staging verification failed")
    return remote


def _stage_job(spec: JobSpec, inputs: dict[str, dict[str, Any]], host: HostSpec, *, ssh: str, scp: str,
               ssh_options: list[str], stage_timeout: float) -> dict[str, Any]:
    job = json.loads(json.dumps(spec.job))
    image = job["image"]
    for field_name, info in inputs.items():
        source = info["path"]
        digest = info["sha256"]
        staged = (_stage_local(host, source, digest) if host.transport == "local"
                  else _stage_ssh(host, source, digest, ssh=ssh, scp=scp, ssh_options=ssh_options, timeout=stage_timeout))
        if field_name == "image.path":
            image["path"] = staged
        elif field_name == "image.data_path":
            image["data_path"] = staged
    return job


def _run_host_job(host: HostSpec, job: dict[str, Any], *, ssh: str, ssh_options: list[str], timeout: float) -> tuple[dict[str, Any], bool, float, str]:
    started = time.monotonic()
    worker_argv = [host.worker, "--ppc-lab", host.ppc_lab, "--base-dir", host.root,
                   "--root", host.root, "--timeout", str(timeout), "run", "-"]
    if host.transport == "local":
        command = worker_argv
    else:
        command = _ssh_cmd(ssh, ssh_options, host, worker_argv)
    try:
        proc = _run(command, input_text=json.dumps(job), timeout=timeout + 10.0)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        return ({"schema": WORKER_RESPONSE_SCHEMA, "id": job.get("id"), "ok": False, "exit_code": None,
                 "timed_out": True, "error": "fleet transport timeout"}, True, elapsed, "transport-timeout")
    elapsed = time.monotonic() - started
    if proc.returncode not in (0, 1):
        return ({"schema": WORKER_RESPONSE_SCHEMA, "id": job.get("id"), "ok": False, "exit_code": None,
                 "timed_out": False, "error": f"worker transport exit {proc.returncode}",
                 "stdout": proc.stdout, "stderr": proc.stderr}, True, elapsed, "transport-exit")
    try:
        response = json.loads(proc.stdout)
    except Exception as exc:
        return ({"schema": WORKER_RESPONSE_SCHEMA, "id": job.get("id"), "ok": False, "exit_code": None,
                 "timed_out": False, "error": f"invalid worker response: {exc}",
                 "stdout": proc.stdout, "stderr": proc.stderr}, True, elapsed, "transport-json")
    if not isinstance(response, dict) or response.get("schema") != WORKER_RESPONSE_SCHEMA:
        return ({"schema": WORKER_RESPONSE_SCHEMA, "id": job.get("id"), "ok": False, "exit_code": None,
                 "timed_out": False, "error": "unsupported worker response"}, True, elapsed, "transport-schema")
    retryable = bool(response.get("timed_out"))
    return response, retryable, elapsed, "worker"


def _cache_key(spec: JobSpec, engine_version: str, inputs: dict[str, dict[str, Any]]) -> str:
    portable_inputs = {k: {"logical_path": v["logical_path"], "size": v["size"], "sha256": v["sha256"]} for k, v in inputs.items()}
    material = {"protocol": FLEET_SCHEMA, "job": spec.job, "engine_version": engine_version, "inputs": portable_inputs}
    return hashlib.sha256(_canonical(material)).hexdigest()


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


def _job_backend(spec: JobSpec) -> str:
    execution = spec.job.get("execution")
    return execution.get("backend", "auto") if isinstance(execution, dict) else "auto"


def _eligible_hosts(spec: JobSpec, hosts: list[HostSpec], engine_version: str) -> list[HostSpec]:
    backend = _job_backend(spec)
    eligible: list[HostSpec] = []
    for host in hosts:
        caps = host.capabilities
        if caps is None or caps.get("version") != engine_version:
            continue
        if not spec.required_tags.issubset(host.tags):
            continue
        backends = caps.get("backends", [])
        if backend not in ("auto", "builtin") and backend not in backends:
            continue
        eligible.append(host)
    return eligible


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
    parser = argparse.ArgumentParser(description="Distributed PPC Lab worker-fleet scheduler")
    parser.add_argument("manifest", type=Path, help=f"{FLEET_SCHEMA} JSON manifest")
    parser.add_argument("--out", type=Path, required=True, help="result directory")
    parser.add_argument("--cache", type=Path, help="shared local content-addressed result cache")
    parser.add_argument("--local-root", type=Path, help="restrict source job inputs to this local tree")
    parser.add_argument("--retries", type=int, help="transport/time-out retries (default: manifest.retries or 1)")
    parser.add_argument("--timeout", type=float, help="worker timeout seconds (default: manifest.timeout or 60)")
    parser.add_argument("--probe-timeout", type=float, default=10.0, help="host capability probe timeout (default: 10)")
    parser.add_argument("--stage-timeout", type=float, default=60.0, help="per-file staging timeout (default: 60)")
    parser.add_argument("--ssh", default=os.environ.get("PPC_LAB_SSH", "ssh"), help="ssh executable")
    parser.add_argument("--scp", default=os.environ.get("PPC_LAB_SCP", "scp"), help="scp executable")
    parser.add_argument("--ssh-option", action="append", default=[], help="extra ssh -o option value (repeatable)")
    parser.add_argument("--no-resume", action="store_true", help="ignore valid records already present in --out")
    parser.add_argument("--evidence-store", type=Path, help="ingest the completed fleet result directory into a PPC Lab evidence store")
    args = parser.parse_args()

    if args.retries is not None and args.retries < 0:
        parser.error("--retries must be non-negative")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.probe_timeout <= 0 or args.stage_timeout <= 0:
        parser.error("probe/stage timeouts must be greater than zero")

    manifest_path = args.manifest.expanduser().resolve()
    try:
        manifest, hosts, jobs = _load_manifest(manifest_path)
        local_root = args.local_root.expanduser().resolve(strict=True) if args.local_root else None
        if local_root is not None and not local_root.is_dir():
            raise FleetError("--local-root is not a directory")
        fingerprints = {spec.name: _job_inputs(spec, local_root) for spec in jobs}
    except (FleetError, FileNotFoundError) as exc:
        print(f"ppc-lab-fleet: {exc}", file=sys.stderr)
        return 2

    retries = args.retries if args.retries is not None else int(manifest.get("retries", 1))
    timeout = args.timeout if args.timeout is not None else float(manifest.get("timeout", 60.0))
    ssh_options = ["-o", "BatchMode=yes", "-o", f"ConnectTimeout={max(1, int(args.probe_timeout))}"]
    for option in args.ssh_option:
        ssh_options += ["-o", option]

    for host in hosts:
        _probe_host(host, ssh=args.ssh, ssh_options=ssh_options, probe_timeout=args.probe_timeout)
    healthy = [host for host in hosts if host.capabilities is not None]
    if not healthy:
        print("ppc-lab-fleet: no healthy hosts", file=sys.stderr)
        for host in hosts:
            print(f"  {host.name}: {host.error}", file=sys.stderr)
        return 2
    engine_version = str(healthy[0].capabilities.get("version"))
    compatible = [host for host in healthy if host.capabilities.get("version") == engine_version]
    for host in healthy:
        if host.capabilities.get("version") != engine_version:
            host.error = f"engine version mismatch: {host.capabilities.get('version')} != {engine_version}"
            host.capabilities = None
    if not compatible:
        print("ppc-lab-fleet: no version-compatible hosts", file=sys.stderr)
        return 2

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = args.cache.expanduser().resolve() if args.cache else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    planned: list[tuple[JobSpec, str, Path, list[HostSpec]]] = []
    summary_rows: list[dict[str, Any] | None] = [None] * len(jobs)
    counters = {"executed": 0, "resumed": 0, "cache_hits": 0, "failed": 0}
    lock = threading.Lock()

    for spec in jobs:
        eligible = _eligible_hosts(spec, hosts, engine_version)
        if not eligible:
            print(f"ppc-lab-fleet: job {spec.name}: no compatible host for tags/backend", file=sys.stderr)
            return 2
        key = _cache_key(spec, engine_version, fingerprints[spec.name])
        result_file = out / f"{spec.index:04d}-{_safe_name(spec.name)}.json"
        record = None if args.no_resume else _valid_record(result_file, key)
        if record is not None:
            counters["resumed"] += 1
            resumed_ok = bool(record["response"].get("ok"))
            if not resumed_ok:
                counters["failed"] += 1
            summary_rows[spec.index] = {"name": spec.name, "file": result_file.name, "status": "resumed",
                                        "ok": resumed_ok, "host": record.get("host"), "cache_key": key}
            continue
        cache_file = cache / f"{key}.json" if cache is not None else None
        cached = _valid_record(cache_file, key) if cache_file is not None else None
        if cached is not None and not bool(cached["response"].get("ok")):
            cached = None
        if cached is not None:
            _atomic_json(result_file, cached)
            counters["cache_hits"] += 1
            summary_rows[spec.index] = {"name": spec.name, "file": result_file.name, "status": "cache-hit",
                                        "ok": bool(cached["response"].get("ok")), "host": cached.get("host"), "cache_key": key}
            continue
        planned.append((spec, key, result_file, eligible))

    def execute(item: tuple[JobSpec, str, Path, list[HostSpec]]) -> None:
        spec, key, result_file, eligible = item
        attempts: list[dict[str, Any]] = []
        final_response: dict[str, Any] | None = None
        final_host: str | None = None
        # Rotate initial host by job index for deterministic load spreading.
        ordered = eligible[spec.index % len(eligible):] + eligible[:spec.index % len(eligible)]
        max_attempts = 1 + retries
        for attempt_index in range(max_attempts):
            host = ordered[attempt_index % len(ordered)]
            with host.semaphore:
                try:
                    staged_job = _stage_job(spec, fingerprints[spec.name], host, ssh=args.ssh, scp=args.scp,
                                            ssh_options=ssh_options, stage_timeout=args.stage_timeout)
                    response, retryable, elapsed, layer = _run_host_job(host, staged_job, ssh=args.ssh,
                                                                         ssh_options=ssh_options, timeout=timeout)
                    attempts.append({"host": host.name, "elapsed_seconds": round(elapsed, 6), "layer": layer,
                                     "retryable": retryable, "ok": bool(response.get("ok")),
                                     "timed_out": bool(response.get("timed_out"))})
                    final_response = response
                    final_host = host.name
                    if not retryable:
                        break
                except Exception as exc:
                    attempts.append({"host": host.name, "elapsed_seconds": 0.0, "layer": "staging",
                                     "retryable": True, "ok": False, "error": str(exc)})
                    final_response = {"schema": WORKER_RESPONSE_SCHEMA, "id": spec.job.get("id"), "ok": False,
                                      "exit_code": None, "timed_out": False, "error": str(exc)}
                    final_host = host.name
                    if attempt_index + 1 >= max_attempts:
                        break
        assert final_response is not None
        portable_inputs = {k: {"logical_path": v["logical_path"], "size": v["size"], "sha256": v["sha256"]}
                           for k, v in fingerprints[spec.name].items()}
        record = {"schema": JOB_RESULT_SCHEMA, "name": spec.name, "source": spec.source, "cache_key": key,
                  "engine_version": engine_version, "host": final_host, "attempts": attempts,
                  "inputs": portable_inputs, "response": final_response}
        _atomic_json(result_file, record)
        if cache is not None and bool(final_response.get("ok")):
            _atomic_json(cache / f"{key}.json", record)
        with lock:
            counters["executed"] += 1
            if not final_response.get("ok"):
                counters["failed"] += 1
            summary_rows[spec.index] = {"name": spec.name, "file": result_file.name, "status": "executed",
                                        "ok": bool(final_response.get("ok")), "host": final_host, "cache_key": key,
                                        "attempts": len(attempts)}

    if planned:
        total_slots = sum(host.slots for host in compatible)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, total_slots)) as pool:
            futures = [pool.submit(execute, item) for item in planned]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"ppc-lab-fleet: internal scheduling failure: {exc}", file=sys.stderr)
                    return 3

    host_rows = []
    for host in hosts:
        caps = host.capabilities
        host_rows.append({"name": host.name, "transport": host.transport, "endpoint": host.endpoint,
                          "slots": host.slots, "tags": sorted(host.tags), "healthy": caps is not None,
                          "version": caps.get("version") if caps else None, "backends": caps.get("backends") if caps else None,
                          "error": host.error})
    summary = {"schema": SUMMARY_SCHEMA, "engine_version": engine_version, "jobs": len(jobs), **counters,
               "hosts": host_rows, "results": summary_rows}
    if args.evidence_store is not None:
        summary["evidence_store"] = str(args.evidence_store.expanduser().resolve())
    _atomic_json(out / "summary.json", summary)
    if args.evidence_store is not None:
        ok, detail = _publish_evidence(args.evidence_store.expanduser().resolve(), out)
        if not ok:
            print(f"ppc-lab-fleet: evidence ingestion failed: {detail}", file=sys.stderr)
            return 2
    print(json.dumps(summary, sort_keys=True))
    return 1 if counters["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
