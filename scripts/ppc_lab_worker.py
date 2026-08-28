#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab transport-neutral JSON/NDJSON worker.

The worker is intentionally a small standard-library adapter around the stable
ppc-lab CLI. Client projects depend on ppc-lab-job-v1 rather than reproducing
CLI argument construction. It is suitable for local subprocesses, SSH pipes,
CI workers, containers, or a future network transport.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

JOB_SCHEMA = "ppc-lab-job-v1"
RESPONSE_SCHEMA = "ppc-lab-worker-response-v1"


class JobError(RuntimeError):
    pass


def _string_number(value: Any, field: str) -> str:
    if isinstance(value, bool):
        raise JobError(f"{field} must be an integer or numeric string")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise JobError(f"{field} must be an integer or numeric string")


def _float_string(value: Any, field: str) -> str:
    if isinstance(value, bool):
        raise JobError(f"{field} must be numeric")
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise JobError(f"{field} must be numeric")


def _resolve_input(path_value: Any, base_dir: Path, root: Path | None, field: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise JobError(f"{field} must be a non-empty path string")
    path = Path(path_value)
    if not path.is_absolute():
        path = base_dir / path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise JobError(f"{field} does not exist: {path}") from exc
    if not resolved.is_file():
        raise JobError(f"{field} is not a file: {resolved}")
    if root is not None:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise JobError(f"{field} is outside worker root: {resolved}") from exc
    return resolved


def _expect_dict(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise JobError(f"{field} must be an object")
    return value


def build_run_args(job: dict[str, Any], base_dir: Path, root: Path | None) -> list[str]:
    if job.get("schema") != JOB_SCHEMA:
        raise JobError(f"schema must be {JOB_SCHEMA}")
    operation = job.get("operation", "run")
    if operation != "run":
        raise JobError(f"unsupported operation: {operation!r}")

    image = _expect_dict(job.get("image"), "image")
    path = _resolve_input(image.get("path"), base_dir, root, "image.path")
    kind = image.get("kind", "auto")
    image_flags = {"auto": "--image", "raw": "--code", "elf": "--elf", "macho": "--macho", "pef": "--pef"}
    if kind not in image_flags:
        raise JobError("image.kind must be one of auto, raw, elf, macho, pef")
    args = ["run", image_flags[kind], str(path)]

    data_path = image.get("data_path")
    if data_path is not None:
        args += ["--data", str(_resolve_input(data_path, base_dir, root, "image.data_path"))]

    image_numeric = {
        "image_base": "--image-base",
        "code_base": "--code-base",
        "data_base": "--data-base",
        "data_map_size": "--data-map-size",
        "heap_base": "--heap-base",
        "heap_size": "--heap-size",
        "stack_base": "--stack-base",
        "stack_size": "--stack-size",
    }
    for key, flag in image_numeric.items():
        if key in image:
            args += [flag, _string_number(image[key], f"image.{key}")]

    execution = _expect_dict(job.get("execution"), "execution")
    backend = execution.get("backend", "auto")
    if backend not in ("auto", "builtin", "unicorn"):
        raise JobError("execution.backend must be auto, builtin, or unicorn")
    args += ["--backend", backend]

    execution_numeric = {
        "entry": "--entry",
        "toc": "--toc",
        "transition_vector": "--transition-vector",
        "import_base": "--import-base",
        "import_size": "--import-size",
        "return_address": "--return",
        "max_instructions": "--max-instructions",
        "default_syscall_return": "--default-syscall-return",
    }
    for key, flag in execution_numeric.items():
        if key in execution:
            args += [flag, _string_number(execution[key], f"execution.{key}")]
    if "entry_symbol" in execution:
        value = execution["entry_symbol"]
        if not isinstance(value, str) or not value:
            raise JobError("execution.entry_symbol must be a non-empty string")
        args += ["--entry-symbol", value]
    if execution.get("trace") is True:
        args.append("--trace")
    elif "trace" in execution and execution.get("trace") is not False:
        raise JobError("execution.trace must be boolean")
    if execution.get("ignore_traps") is True:
        args.append("--ignore-traps")
    elif "ignore_traps" in execution and execution.get("ignore_traps") is not False:
        raise JobError("execution.ignore_traps must be boolean")
    if "trace_range" in execution:
        value = execution["trace_range"]
        if not isinstance(value, str) or ":" not in value:
            raise JobError("execution.trace_range must be START:END")
        args += ["--trace-range", value]

    registers = _expect_dict(job.get("registers"), "registers")
    for name, value in registers.items():
        if not isinstance(name, str) or not name.startswith("r") or not name[1:].isdigit() or not 0 <= int(name[1:]) < 32:
            raise JobError(f"invalid GPR name: {name!r}")
        args += ["--set", f"{name}={_string_number(value, f'registers.{name}')}" ]

    fregisters = _expect_dict(job.get("float_registers"), "float_registers")
    for name, value in fregisters.items():
        if not isinstance(name, str) or not name.startswith("f") or not name[1:].isdigit() or not 0 <= int(name[1:]) < 32:
            raise JobError(f"invalid FPR name: {name!r}")
        args += ["--set-f", f"{name}={_float_string(value, f'float_registers.{name}')}" ]

    bindings = _expect_dict(job.get("bindings"), "bindings")
    for name, value in bindings.items():
        if not isinstance(name, str) or not name:
            raise JobError("binding names must be non-empty strings")
        args += ["--bind", f"{name}={_string_number(value, f'bindings.{name}')}" ]

    writes_u32 = _expect_dict(job.get("writes_u32"), "writes_u32")
    for address, value in writes_u32.items():
        args += ["--write-u32", f"{_string_number(address, 'writes_u32 address')}={_string_number(value, f'writes_u32.{address}')}" ]

    writes_f32 = _expect_dict(job.get("writes_f32"), "writes_f32")
    for address, value in writes_f32.items():
        args += ["--write-f32", f"{_string_number(address, 'writes_f32 address')}={_float_string(value, f'writes_f32.{address}')}" ]

    stubs = job.get("stubs", [])
    if not isinstance(stubs, list) or any(not isinstance(item, str) or "@" not in item for item in stubs):
        raise JobError("stubs must be an array of KIND@ADDRESS strings")
    for stub in stubs:
        args += ["--stub", stub]

    syscall_returns = _expect_dict(job.get("syscall_returns"), "syscall_returns")
    for number, value in syscall_returns.items():
        args += ["--syscall-return", f"{_string_number(number, 'syscall number')}={_string_number(value, f'syscall_returns.{number}')}" ]

    dumps = job.get("dumps", [])
    if not isinstance(dumps, list):
        raise JobError("dumps must be an array")
    for index, dump in enumerate(dumps):
        if not isinstance(dump, dict) or "address" not in dump or "size" not in dump:
            raise JobError(f"dumps[{index}] must contain address and size")
        args += ["--dump", f"{_string_number(dump['address'], f'dumps[{index}].address')}:{_string_number(dump['size'], f'dumps[{index}].size')}" ]
    return args


def _response(job_id: Any, *, ok: bool, exit_code: int | None = None, error: str | None = None,
              timed_out: bool = False, result: Any = None, snapshot: Any = None,
              stdout: str = "", stderr: str = "", command: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": RESPONSE_SCHEMA,
        "id": job_id,
        "ok": ok,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    if error is not None:
        value["error"] = error
    if result is not None:
        value["result"] = result
    if snapshot is not None:
        value["snapshot"] = snapshot
    if stdout:
        value["stdout"] = stdout
    if stderr:
        value["stderr"] = stderr
    if command is not None:
        value["command"] = command
    return value


def run_job(job: Any, *, ppc_lab: Path, base_dir: Path, root: Path | None,
            timeout: float, expose_command: bool) -> dict[str, Any]:
    job_id = job.get("id") if isinstance(job, dict) else None
    if not isinstance(job, dict):
        return _response(job_id, ok=False, error="job must be a JSON object")
    try:
        cli_args = build_run_args(job, base_dir, root)
    except JobError as exc:
        return _response(job_id, ok=False, error=str(exc))

    with tempfile.TemporaryDirectory(prefix="ppc-lab-worker-") as td:
        temp = Path(td)
        result_path = temp / "result.json"
        snapshot_path = temp / "snapshot.json"
        command = [str(ppc_lab), *cli_args, "--json", str(result_path), "--snapshot", str(snapshot_path)]
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return _response(job_id, ok=False, timed_out=True, error=f"worker timeout after {timeout:g}s",
                             stdout=stdout, stderr=stderr, command=command if expose_command else None)
        result = None
        snapshot = None
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as exc:  # malformed tool output is a worker failure
                return _response(job_id, ok=False, exit_code=proc.returncode,
                                 error=f"cannot decode PPC Lab result: {exc}", stdout=proc.stdout,
                                 stderr=proc.stderr, command=command if expose_command else None)
        if snapshot_path.is_file():
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return _response(job_id, ok=False, exit_code=proc.returncode,
                                 error=f"cannot decode PPC Lab snapshot: {exc}", stdout=proc.stdout,
                                 stderr=proc.stderr, command=command if expose_command else None)
        ok = proc.returncode == 0
        error = None if ok else (result.get("stop_reason") if isinstance(result, dict) else "ppc-lab execution failed")
        return _response(job_id, ok=ok, exit_code=proc.returncode, error=error,
                         result=result, snapshot=snapshot, stdout=proc.stdout, stderr=proc.stderr,
                         command=command if expose_command else None)


def _find_ppc_lab(value: str | None) -> Path:
    candidate = value or os.environ.get("PPC_LAB_BIN") or shutil.which("ppc-lab")
    if not candidate:
        raise SystemExit("ppc-lab-worker: cannot find ppc-lab; use --ppc-lab or PPC_LAB_BIN")
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"ppc-lab-worker: ppc-lab is not a file: {path}")
    return path


def _root(value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"ppc-lab-worker: --root is not a directory: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="PPC Lab JSON/NDJSON execution worker")
    parser.add_argument("--ppc-lab", help="path to ppc-lab (default: PPC_LAB_BIN or PATH)")
    parser.add_argument("--root", help="restrict job input files to this directory tree")
    parser.add_argument("--timeout", type=float, default=60.0, help="wall-clock timeout per job in seconds (default: 60)")
    parser.add_argument("--expose-command", action="store_true", help="include the local ppc-lab argv in responses (debugging only)")
    sub = parser.add_subparsers(dest="mode", required=True)
    run_parser = sub.add_parser("run", help="execute one JSON job")
    run_parser.add_argument("job", help="job JSON file or - for stdin")
    sub.add_parser("stream", help="process newline-delimited JSON jobs from stdin")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    ppc_lab = _find_ppc_lab(args.ppc_lab)
    root = _root(args.root)

    if args.mode == "run":
        if args.job == "-":
            base_dir = root or Path.cwd().resolve()
            try:
                job = json.load(sys.stdin)
            except Exception as exc:
                print(json.dumps(_response(None, ok=False, error=f"invalid JSON: {exc}"), sort_keys=True))
                return 1
        else:
            job_path = Path(args.job).expanduser().resolve()
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(json.dumps(_response(None, ok=False, error=f"cannot read job: {exc}"), sort_keys=True))
                return 1
            base_dir = job_path.parent
        response = run_job(job, ppc_lab=ppc_lab, base_dir=base_dir, root=root,
                           timeout=args.timeout, expose_command=args.expose_command)
        print(json.dumps(response, sort_keys=True))
        return 0 if response.get("ok") else 1

    base_dir = root or Path.cwd().resolve()
    had_transport_error = False
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception as exc:
            response = _response(None, ok=False, error=f"invalid JSON: {exc}")
            had_transport_error = True
        else:
            response = run_job(job, ppc_lab=ppc_lab, base_dir=base_dir, root=root,
                               timeout=args.timeout, expose_command=args.expose_command)
        print(json.dumps(response, sort_keys=True), flush=True)
    # Individual job failures do not terminate or fail a stream worker. Only malformed
    # transport JSON changes the process status, making long-lived pipes resilient.
    return 2 if had_transport_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
