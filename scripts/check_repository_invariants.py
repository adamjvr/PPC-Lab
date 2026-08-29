#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Cross-platform repository invariants for PPC Lab.

This is intentionally dependency-free so the public CI can enforce the most
important long-term architecture/licensing rules without custom tooling.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPDX = "SPDX-License-Identifier: GPL-3.0-only"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_license() -> None:
    path = ROOT / "LICENSE"
    if not path.is_file():
        fail("LICENSE is missing")
    text = path.read_text(encoding="utf-8", errors="replace")
    if "GNU GENERAL PUBLIC LICENSE" not in text or "Version 3, 29 June 2007" not in text:
        fail("LICENSE is not the canonical GNU GPL v3 text")


def check_spdx() -> None:
    required: list[Path] = []
    required.extend(ROOT.glob("src/*.cpp"))
    required.extend(ROOT.glob("tools/*.cpp"))
    required.extend(ROOT.glob("tests/*.cpp"))
    required.extend(ROOT.glob("include/**/*.hpp"))
    required.extend(ROOT.glob("scripts/*.py"))
    required.extend(ROOT.glob("scripts/*.sh"))
    required.extend(ROOT.glob("tests/*.py"))
    required.extend(ROOT.glob("integrations/**/*.py"))
    required.extend(ROOT.glob("Tools/*.command"))
    required.extend(ROOT.glob("profiles/*/scripts/*.sh"))
    required.extend(path for path in (ROOT / "cmake").glob("*") if path.is_file())
    required.extend([ROOT / "CMakeLists.txt", ROOT / ".github/workflows/ci.yml"])

    missing = []
    for path in required:
        if not path.is_file():
            continue
        head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:5])
        if SPDX not in head:
            missing.append(path.relative_to(ROOT).as_posix())
    if missing:
        fail("missing GPL-3.0-only SPDX header: " + ", ".join(sorted(missing)))




def check_version_sync() -> None:
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8", errors="replace")
    match = re.search(r"project\(PPCLab VERSION ([0-9]+\.[0-9]+\.[0-9]+)", cmake)
    if not match:
        fail("cannot determine project version from CMakeLists.txt")
    version = match.group(1)
    cli = (ROOT / "tools" / "ppc_lab.cpp").read_text(encoding="utf-8", errors="replace")
    if 'PPC_LAB_VERSION="${PROJECT_VERSION}"' not in cmake or "kVersion = PPC_LAB_VERSION" not in cli:
        fail(f"CLI version is not sourced from the CMake project version {version}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    if f"## {version} " not in changelog:
        fail(f"CHANGELOG.md has no release heading for {version}")
    platform = (ROOT / "scripts" / "ppc_lab_platform.py").read_text(encoding="utf-8", errors="replace")
    if f'PLATFORM_VERSION = "{version}"' not in platform:
        fail(f"ppc-lab-platform version is not synchronized to {version}")


def check_lts_contract() -> None:
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8", errors="replace")
    version_template = (ROOT / "cmake" / "Version.hpp.in").read_text(encoding="utf-8", errors="replace")
    required = {
        "PPCLAB_CPP_API_VERSION": "1",
        "PPCLAB_CPP_ABI_VERSION": "1",
        "PPCLAB_TARGET_PROFILE_API_VERSION": "1",
        "PPCLAB_RELEASE_API_VERSION": "1",
        "PPCLAB_COMPATIBILITY_API_VERSION": "1",
        "PPCLAB_BACKUP_API_VERSION": "1",
        "PPCLAB_UPGRADE_API_VERSION": "1",
        "PPCLAB_OBSERVABILITY_API_VERSION": "1",
        "PPCLAB_SECURITY_API_VERSION": "1",
        "PPCLAB_REPLICATION_API_VERSION": "1",
    }
    for macro, value in required.items():
        if f"#define {macro} {value}" not in version_template:
            fail(f"public compatibility contract missing {macro}={value}")
    for tool in ("ppc_lab_target.py", "ppc_lab_release.py", "ppc_lab_compat.py", "ppc_lab_support.py", "ppc_lab_deploy.py", "ppc_lab_backup.py", "ppc_lab_upgrade.py", "ppc_lab_observe.py", "ppc_lab_security.py", "ppc_lab_replicate.py"):
        if f"scripts/{tool}" not in cmake:
            fail(f"CMake install contract is missing {tool}")
    for schema in (
        "ppc-lab-target-profile-v1.schema.json",
        "ppc-lab-target-profile-package-v1.schema.json",
        "ppc-lab-release-manifest-v1.schema.json",
        "ppc-lab-release-qualification-v1.schema.json",
        "ppc-lab-compatibility-snapshot-v1.schema.json",
        "ppc-lab-support-report-v1.schema.json",
        "ppc-lab-support-bundle-v1.schema.json",
        "ppc-lab-deployment-v1.schema.json",
        "ppc-lab-deployment-report-v1.schema.json",
        "ppc-lab-backup-v1.schema.json",
        "ppc-lab-backup-report-v1.schema.json",
        "ppc-lab-upgrade-plan-v1.schema.json",
        "ppc-lab-upgrade-transaction-v1.schema.json",
        "ppc-lab-release-channel-v1.schema.json",
        "ppc-lab-observability-store-v1.schema.json",
        "ppc-lab-observation-v1.schema.json",
        "ppc-lab-observability-report-v1.schema.json",
        "ppc-lab-observability-policy-v1.schema.json",
        "ppc-lab-observability-check-v1.schema.json",
        "ppc-lab-capacity-report-v1.schema.json",
        "ppc-lab-auth-store-v1.schema.json",
        "ppc-lab-audit-record-v1.schema.json",
        "ppc-lab-replication-store-v1.schema.json",
        "ppc-lab-replication-bundle-v1.schema.json",
        "ppc-lab-replication-receipt-v1.schema.json",
        "ppc-lab-replication-status-v1.schema.json",
        "ppc-lab-replication-verify-v1.schema.json",
    ):
        if not (ROOT / "schemas" / schema).is_file():
            fail(f"missing v3 LTS schema: {schema}")

def check_target_neutral_core() -> None:
    roots = ["include", "src", "tools", "scripts", "tests", "cmake", "integrations"]
    files: list[Path] = []
    for name in roots:
        base = ROOT / name
        if base.exists():
            files.extend(
                path for path in base.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
            )
    files.extend([ROOT / "CMakeLists.txt", ROOT / ".github/workflows/ci.yml"])

    # These are deliberate regression sentinels for the first extracted target.
    # Generic code/tooling must never acquire them.
    forbidden = ["rebirth", "x0x", "0x10000cf4", "0x418c9e14a76a422e"]
    hits: list[str] = []
    self_path = Path(__file__).resolve()
    for path in files:
        if path.resolve() == self_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in forbidden:
            if token in text:
                hits.append(f"{path.relative_to(ROOT).as_posix()} contains {token}")
    if hits:
        fail("target-specific material leaked into generic core/tooling: " + "; ".join(hits))


def main() -> int:
    check_license()
    check_spdx()
    check_version_sync()
    check_lts_contract()
    check_target_neutral_core()
    print("PASS: GPLv3/SPDX, version/LTS contract sync, and target-neutral core invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
