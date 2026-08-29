#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import json
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "ppc_lab_release.py"

spec = importlib.util.spec_from_file_location("ppclab_release_certification_test", MODULE)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

orig_qualify = mod.qualify_release
try:
    mod.qualify_release = lambda root, build_dir, **kwargs: {
        "schema": mod.QUALIFICATION_SCHEMA,
        "release_api": mod.API_VERSION,
        "platform_version": mod.project_version(root),
        "ok": True,
        "source": {"manifest": "RELEASE-MANIFEST.json", "manifest_sha256": mod.sha256_file(root / "RELEASE-MANIFEST.json"), "license": "GPL-3.0-only"},
        "environment": {},
        "configuration": {"config": kwargs.get("config", "Release"), "unicorn": kwargs.get("unicorn", False), "build_dir": "$BUILD"},
        "required_tests": list(mod.QUALIFICATION_REQUIRED_TESTS),
        "checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="ppclab-certification-test-") as raw:
        td = Path(raw)
        archive = td / "PPC-Lab-source.zip"
        workspace = td / "workspace"
        doc = mod.certify_release(ROOT, archive, workspace, epoch=946684800)
        assert doc["schema"] == "ppc-lab-release-certification-v1"
        assert doc["release_api"] == 1 and doc["platform_version"] == "3.9.4"
        assert doc["ok"] is True
        assert archive.is_file() and doc["archive"]["sha256"] == mod.sha256_file(archive)
        assert doc["archive"]["manifest_sha256"] == doc["source"]["manifest_sha256"]
        assert doc["archive"]["name"] == archive.name
        assert doc["qualification"]["ok"] is True
        assert all(check["ok"] for check in doc["checks"])
        extracted = workspace / "source"
        assert (extracted / "RELEASE-MANIFEST.json").is_file()
        assert mod.verify(extracted, json.loads((extracted / "RELEASE-MANIFEST.json").read_text()), extracted / "RELEASE-MANIFEST.json") == []

        assert mod.casefold_collisions(["Tools/build.command", "tools/build.command"]) == [["Tools/build.command", "tools/build.command"]]

        casefold_bad = td / "casefold-bad.zip"
        with zipfile.ZipFile(casefold_bad, "w") as zf:
            zf.writestr("Tools/build.command", b"one")
            zf.writestr("tools/build.command", b"two")
            zf.writestr("RELEASE-MANIFEST.json", b"{}")
        casefold_inspected = mod.inspect_source_archive(casefold_bad)
        assert casefold_inspected["ok"] is False
        assert any("case-fold path collision" in error for error in casefold_inspected["errors"])

        bad = td / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../escape.txt", b"bad")
            zf.writestr("RELEASE-MANIFEST.json", b"{}")
        inspected = mod.inspect_source_archive(bad)
        assert inspected["ok"] is False
        assert any("unsafe archive member path" in error for error in inspected["errors"])
        try:
            mod.extract_source_archive(bad, td / "bad-extract")
        except mod.ReleaseError:
            pass
        else:
            raise AssertionError("unsafe archive extraction was not rejected")
finally:
    mod.qualify_release = orig_qualify

print("PASS: exact source archive certification and safe clean extraction")
