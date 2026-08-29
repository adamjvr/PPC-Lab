#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Deterministic PPC Lab release manifest, archive, and qualification tooling."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Sequence

MANIFEST_SCHEMA = "ppc-lab-release-manifest-v1"
QUALIFICATION_SCHEMA = "ppc-lab-release-qualification-v1"
API_VERSION = 1
EXCLUDE_DIRS = {
    ".git", "build", "build-release", "build-asan", "build-debug", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip", ".tar", ".gz", ".xz", ".7z"}
QUALIFICATION_REQUIRED_TESTS = (
    "ppc_lab_repository_invariants",
    "ppc_lab_install_contract",
    "ppc_lab_cli_selftest",
    "ppc_lab_release_engineering",
    "ppc_lab_release_qualification",
    "ppc_lab_compatibility_assurance",
    "ppc_lab_replication",
)


class ReleaseError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def project_version(root: Path) -> str:
    text = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    m = re.search(r"project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)", text)
    if not m:
        raise ReleaseError("cannot determine project version")
    return m.group(1)


def compatibility_snapshot(root: Path) -> dict[str, Any]:
    module_path = root / "scripts" / "ppc_lab_compat.py"
    if not module_path.is_file():
        raise ReleaseError("missing scripts/ppc_lab_compat.py")
    spec = importlib.util.spec_from_file_location("ppclab_release_compat", module_path)
    if spec is None or spec.loader is None:
        raise ReleaseError("cannot load compatibility module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_snapshot(root)


def source_files(root: Path, extra_exclude: set[Path] | None = None) -> list[Path]:
    root = root.resolve()
    excluded = {p.resolve() for p in (extra_exclude or set())}
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root)
        if rel.as_posix() == "RELEASE-MANIFEST.json":
            continue
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if p.resolve() in excluded:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def mode_for(path: Path) -> str:
    return "0755" if os.access(path, os.X_OK) else "0644"


def build_manifest(root: Path, *, extra_exclude: set[Path] | None = None) -> dict[str, Any]:
    files = source_files(root, extra_exclude)
    return {
        "schema": MANIFEST_SCHEMA,
        "release_api": API_VERSION,
        "version": project_version(root),
        "license": "GPL-3.0-only",
        "cpp_api": 1,
        "cpp_abi": 1,
        "target_profile_api": 1,
        "compatibility": compatibility_snapshot(root),
        "files": [
            {
                "path": p.relative_to(root).as_posix(),
                "size": p.stat().st_size,
                "mode": mode_for(p),
                "sha256": sha256_file(p),
            }
            for p in files
        ],
    }


def write_manifest(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify(root: Path, manifest: dict[str, Any], manifest_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA}")
    try:
        if manifest.get("version") != project_version(root):
            errors.append("manifest version does not match CMake project version")
    except (OSError, ReleaseError) as exc:
        errors.append(str(exc))
    listed = {x.get("path"): x for x in manifest.get("files", []) if isinstance(x, dict)}
    exclude = {manifest_path} if manifest_path else set()
    actual = {p.relative_to(root).as_posix(): p for p in source_files(root, exclude)}
    for rel, p in actual.items():
        item = listed.get(rel)
        if item is None:
            errors.append(f"unlisted source file: {rel}")
            continue
        if item.get("sha256") != sha256_file(p):
            errors.append(f"hash mismatch: {rel}")
        if item.get("size") != p.stat().st_size:
            errors.append(f"size mismatch: {rel}")
    for rel in sorted(set(listed) - set(actual)):
        errors.append(f"manifest references missing/excluded file: {rel}")
    return errors


def zip_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    epoch = max(epoch, 315532800)
    d = dt.datetime.fromtimestamp(epoch, dt.timezone.utc)
    return d.year, d.month, d.day, d.hour, d.minute, d.second - d.second % 2


def create_archive(root: Path, out: Path, epoch: int) -> dict[str, Any]:
    root = root.resolve()
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_manifest = out.parent / (out.name + ".manifest.tmp.json")
    manifest = build_manifest(root, extra_exclude={out, tmp_manifest})
    files = source_files(root, {out, tmp_manifest})
    ztime = zip_time(epoch)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            rel = p.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel, ztime)
            info.create_system = 3
            mode = 0o755 if os.access(p, os.X_OK) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        info = zipfile.ZipInfo("RELEASE-MANIFEST.json", ztime)
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        zf.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return manifest


def _redact(text: str, root: Path, build_dir: Path) -> str:
    replacements = [(str(build_dir.resolve()), "$BUILD"), (str(root.resolve()), "$ROOT")]
    # Windows tools can emit backslash spellings even when Python received slash paths.
    replacements += [(a.replace("/", "\\"), b) for a, b in replacements]
    out = text
    for src, dst in replacements:
        if src:
            out = out.replace(src, dst)
    return out


def _display_command(argv: Sequence[str], root: Path, build_dir: Path) -> list[str]:
    return [_redact(str(x), root, build_dir) for x in argv]


def _run_check(name: str, argv: Sequence[str], root: Path, build_dir: Path) -> dict[str, Any]:
    display = _display_command(argv, root, build_dir)
    try:
        p = subprocess.run(list(argv), cwd=root, text=True, capture_output=True)
        stdout = _redact(p.stdout, root, build_dir)
        stderr = _redact(p.stderr, root, build_dir)
        rec: dict[str, Any] = {
            "name": name,
            "ok": p.returncode == 0,
            "exit_code": p.returncode,
            "command": display,
            "stdout_sha256": sha256_text(stdout),
            "stderr_sha256": sha256_text(stderr),
            "stdout_lines": len(stdout.splitlines()),
            "stderr_lines": len(stderr.splitlines()),
        }
        if p.returncode != 0:
            rec["stdout_tail"] = "\n".join(stdout.splitlines()[-80:])
            rec["stderr_tail"] = "\n".join(stderr.splitlines()[-80:])
        return rec
    except OSError as exc:
        msg = _redact(str(exc), root, build_dir)
        return {
            "name": name,
            "ok": False,
            "exit_code": 127,
            "command": display,
            "stdout_sha256": sha256_text(""),
            "stderr_sha256": sha256_text(msg),
            "stdout_lines": 0,
            "stderr_lines": 1,
            "stderr_tail": msg,
        }


def _tool_version(executable: str, root: Path, build_dir: Path) -> str:
    try:
        p = subprocess.run([executable, "--version"], cwd=root, text=True, capture_output=True)
        text = (p.stdout or p.stderr).strip().splitlines()
        return _redact(text[0] if text else "unknown", root, build_dir)
    except OSError:
        return "unavailable"


def parse_ctest_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        m = re.search(r"Test\s+#\d+:\s+(\S+)", line)
        if m:
            names.add(m.group(1))
    return names


def _run_capture(argv: Sequence[str], root: Path, build_dir: Path) -> tuple[int, str, str]:
    try:
        p = subprocess.run(list(argv), cwd=root, text=True, capture_output=True)
        return p.returncode, _redact(p.stdout, root, build_dir), _redact(p.stderr, root, build_dir)
    except OSError as exc:
        return 127, "", _redact(str(exc), root, build_dir)


def qualify_release(
    root: Path,
    build_dir: Path,
    *,
    cmake: str = "cmake",
    ctest: str = "ctest",
    config: str = "Release",
    unicorn: bool = False,
) -> dict[str, Any]:
    """Run the portable release gate and return target-neutral JSON evidence."""
    root = root.resolve()
    build_dir = build_dir.resolve()
    manifest_path = root / "RELEASE-MANIFEST.json"
    version = project_version(root)
    checks: list[dict[str, Any]] = []

    manifest_errors: list[str] = []
    manifest_sha256: str | None = None
    if not manifest_path.is_file():
        manifest_errors.append("RELEASE-MANIFEST.json is missing")
    else:
        try:
            manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_errors.extend(verify(root, manifest_doc, manifest_path))
            manifest_sha256 = sha256_file(manifest_path)
        except (OSError, json.JSONDecodeError) as exc:
            manifest_errors.append(f"cannot read release manifest: {exc}")
    checks.append({
        "name": "release-manifest",
        "ok": not manifest_errors,
        "errors": manifest_errors,
    })

    build_dir.mkdir(parents=True, exist_ok=True)
    configure_argv = [
        cmake, "-S", str(root), "-B", str(build_dir),
        f"-DPPC_LAB_ENABLE_UNICORN={'ON' if unicorn else 'OFF'}",
        f"-DCMAKE_BUILD_TYPE={config}",
    ]
    configure = _run_check("configure", configure_argv, root, build_dir)
    checks.append(configure)

    discovered: set[str] = set()
    missing_required = list(QUALIFICATION_REQUIRED_TESTS)
    discovery_rec: dict[str, Any]
    if configure["ok"]:
        discover_argv = [ctest, "--test-dir", str(build_dir), "-C", config, "-N"]
        code, out, err = _run_capture(discover_argv, root, build_dir)
        discovered = parse_ctest_names(out)
        missing_required = sorted(set(QUALIFICATION_REQUIRED_TESTS) - discovered)
        discovery_rec = {
            "name": "test-discovery",
            "ok": code == 0 and not missing_required,
            "exit_code": code,
            "command": _display_command(discover_argv, root, build_dir),
            "discovered_tests": len(discovered),
            "required_tests": list(QUALIFICATION_REQUIRED_TESTS),
            "missing_required_tests": missing_required,
            "stdout_sha256": sha256_text(out),
            "stderr_sha256": sha256_text(err),
        }
        if code != 0:
            discovery_rec["stderr_tail"] = "\n".join(err.splitlines()[-80:])
    else:
        discovery_rec = {
            "name": "test-discovery",
            "ok": False,
            "skipped": True,
            "reason": "configure failed",
            "required_tests": list(QUALIFICATION_REQUIRED_TESTS),
            "missing_required_tests": missing_required,
        }
    checks.append(discovery_rec)

    if configure["ok"] and discovery_rec["ok"]:
        build_argv = [cmake, "--build", str(build_dir), "--config", config, "--parallel"]
        build = _run_check("build", build_argv, root, build_dir)
    else:
        build = {"name": "build", "ok": False, "skipped": True, "reason": "pre-build qualification failed"}
    checks.append(build)

    if build["ok"]:
        test_argv = [ctest, "--test-dir", str(build_dir), "-C", config, "--output-on-failure"]
        tests = _run_check("ctest", test_argv, root, build_dir)
    else:
        tests = {"name": "ctest", "ok": False, "skipped": True, "reason": "build failed or was skipped"}
    checks.append(tests)

    ok = all(bool(x.get("ok")) for x in checks)
    return {
        "schema": QUALIFICATION_SCHEMA,
        "release_api": API_VERSION,
        "platform_version": version,
        "ok": ok,
        "source": {
            "manifest": "RELEASE-MANIFEST.json",
            "manifest_sha256": manifest_sha256,
            "license": "GPL-3.0-only",
        },
        "environment": {
            "system": platform.system() or "unknown",
            "machine": platform.machine() or "unknown",
            "python": platform.python_version(),
            "cmake": _tool_version(cmake, root, build_dir),
            "ctest": _tool_version(ctest, root, build_dir),
        },
        "configuration": {
            "config": config,
            "unicorn": unicorn,
            "build_dir": _redact(str(build_dir), root, build_dir),
        },
        "required_tests": list(QUALIFICATION_REQUIRED_TESTS),
        "checks": checks,
    }


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_qualification_failures(doc: dict[str, Any]) -> None:
    for check in doc.get("checks", []):
        if check.get("ok"):
            continue
        print(f"ERROR: qualification check failed: {check.get('name', 'unknown')}", file=sys.stderr)
        for error in check.get("errors", []):
            print(f"  {error}", file=sys.stderr)
        for missing in check.get("missing_required_tests", []):
            print(f"  missing required test: {missing}", file=sys.stderr)
        if check.get("reason"):
            print(f"  {check['reason']}", file=sys.stderr)
        for key in ("stdout_tail", "stderr_tail"):
            tail = check.get(key)
            if tail:
                print(f"  {key}:\n{tail}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("manifest")
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("verify")
    p.add_argument("root", type=Path)
    p.add_argument("manifest", type=Path)
    p = sub.add_parser("archive")
    p.add_argument("root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "946684800")))
    p = sub.add_parser("qualify")
    p.add_argument("root", type=Path)
    p.add_argument("--build-dir", type=Path)
    p.add_argument("--json", type=Path)
    p.add_argument("--cmake", default="cmake")
    p.add_argument("--ctest", default="ctest")
    p.add_argument("--config", default="Release")
    p.add_argument("--unicorn", choices=("on", "off"), default="off")
    ns = ap.parse_args()
    try:
        root = ns.root.resolve()
        if ns.cmd == "manifest":
            out = ns.out.resolve()
            doc = build_manifest(root, extra_exclude={out})
            write_manifest(out, doc)
            print(f"{out} files={len(doc['files'])}")
            return 0
        if ns.cmd == "verify":
            mp = ns.manifest.resolve()
            doc = json.loads(mp.read_text(encoding="utf-8"))
            errors = verify(root, doc, mp if mp.is_relative_to(root) else None)
            if errors:
                for e in errors:
                    print(f"ERROR: {e}", file=sys.stderr)
                return 1
            print(f"PASS: release manifest {doc['version']} files={len(doc['files'])}")
            return 0
        if ns.cmd == "archive":
            manifest = create_archive(root, ns.out, ns.epoch)
            print(f"{ns.out.resolve()} sha256={sha256_file(ns.out.resolve())} files={len(manifest['files'])}")
            return 0
        build_dir = (ns.build_dir or (root / "build" / "qualification")).resolve()
        doc = qualify_release(
            root,
            build_dir,
            cmake=ns.cmake,
            ctest=ns.ctest,
            config=ns.config,
            unicorn=ns.unicorn == "on",
        )
        if ns.json:
            write_json(ns.json.resolve(), doc)
            print(
                f"{'PASS' if doc['ok'] else 'FAIL'}: release qualification "
                f"{doc['platform_version']} report={ns.json.resolve()}"
            )
        else:
            print(json.dumps(doc, indent=2, sort_keys=True))
        if not doc["ok"]:
            print_qualification_failures(doc)
        return 0 if doc["ok"] else 1
    except (ReleaseError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ppc-lab-release: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
