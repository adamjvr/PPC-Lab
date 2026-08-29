#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "ppc_lab_release.py"

spec = importlib.util.spec_from_file_location("ppclab_release_qualification_test", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sample = """
Test project /tmp/build
  Test  #1: ppc_lab_tests
  Test #12: ppc_lab_repository_invariants
  Test #13: ppc_lab_install_contract
  Test #14: ppc_lab_cli_selftest
"""
assert mod.parse_ctest_names(sample) == {
    "ppc_lab_tests",
    "ppc_lab_repository_invariants",
    "ppc_lab_install_contract",
    "ppc_lab_cli_selftest",
}

orig_run_check = mod._run_check
orig_run_capture = mod._run_capture
orig_tool_version = mod._tool_version


def fake_run_check(name, argv, root, build_dir):
    return {
        "name": name,
        "ok": True,
        "exit_code": 0,
        "command": mod._display_command(argv, root, build_dir),
        "stdout_sha256": mod.sha256_text(""),
        "stderr_sha256": mod.sha256_text(""),
        "stdout_lines": 0,
        "stderr_lines": 0,
    }


def discovery(names):
    text = "\n".join(f"  Test #{i}: {name}" for i, name in enumerate(names, 1)) + "\n"
    return 0, text, ""

try:
    mod._run_check = fake_run_check
    mod._tool_version = lambda executable, root, build_dir: f"{executable} fake-1"
    with tempfile.TemporaryDirectory(prefix="ppclab-qualification-test-") as raw:
        build = Path(raw) / "build"
        mod._run_capture = lambda argv, root, build_dir: discovery(mod.QUALIFICATION_REQUIRED_TESTS)
        doc = mod.qualify_release(ROOT, build, cmake="cmake", ctest="ctest")
        assert doc["schema"] == "ppc-lab-release-qualification-v1"
        assert doc["release_api"] == 1 and doc["platform_version"] == "3.9.3"
        assert doc["ok"] is True
        assert doc["source"]["license"] == "GPL-3.0-only"
        assert doc["source"]["manifest_sha256"]
        assert doc["configuration"]["build_dir"] == "$BUILD"
        assert all(check["ok"] for check in doc["checks"])

        missing = mod.QUALIFICATION_REQUIRED_TESTS[:-1]
        mod._run_capture = lambda argv, root, build_dir: discovery(missing)
        failed = mod.qualify_release(ROOT, build, cmake="cmake", ctest="ctest")
        assert failed["ok"] is False
        discover = next(x for x in failed["checks"] if x["name"] == "test-discovery")
        assert discover["missing_required_tests"] == [mod.QUALIFICATION_REQUIRED_TESTS[-1]]
        assert next(x for x in failed["checks"] if x["name"] == "build")["skipped"] is True
finally:
    mod._run_check = orig_run_check
    mod._run_capture = orig_run_capture
    mod._tool_version = orig_tool_version

print("PASS: portable release qualification report and critical-test gate")
