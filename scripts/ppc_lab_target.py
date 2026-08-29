#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""PPC Lab target-profile SDK.

Creates, validates, inspects, and reproducibly packages target adapters without
copying private target binaries into PPC Lab source trees or profile archives.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any

SCHEMA = "ppc-lab-target-profile-v1"
PACKAGE_SCHEMA = "ppc-lab-target-profile-package-v1"
PROFILE_API_VERSION = 1
DEFAULT_MINIMUM = "3.1.0"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SKIP_PARTS = {".git", "__pycache__", "build", ".DS_Store"}
BINARY_SUFFIXES = {
    ".exe", ".dll", ".dylib", ".so", ".bin", ".rom", ".img", ".iso", ".dmg",
    ".elf", ".pef", ".app", ".sit", ".hqx", ".zip", ".7z", ".rar",
}

class ProfileError(RuntimeError):
    pass

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def safe_rel(value: str) -> str:
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ProfileError(f"unsafe relative path: {value}")
    return p.as_posix()

def semver_tuple(value: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", value)
    if not m:
        raise ProfileError(f"invalid semantic version: {value}")
    return tuple(map(int, m.groups()))  # type: ignore[return-value]

def validate_doc(doc: Any, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["profile must be a JSON object"]
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    ident = doc.get("id")
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
        errors.append("id must match [a-z0-9][a-z0-9._-]{0,63}")
    if not isinstance(doc.get("name"), str) or not doc.get("name", "").strip():
        errors.append("name must be a non-empty string")
    try:
        semver_tuple(str(doc.get("minimum_ppc_lab", "")))
    except ProfileError as exc:
        errors.append(str(exc))
    arch = doc.get("architecture")
    if not isinstance(arch, dict) or arch.get("guest") != "ppc32" or arch.get("endian") != "big":
        errors.append("architecture must declare guest=ppc32 and endian=big")
    inputs = doc.get("inputs", [])
    if not isinstance(inputs, list):
        errors.append("inputs must be an array")
    else:
        seen: set[str] = set()
        for i, item in enumerate(inputs):
            if not isinstance(item, dict):
                errors.append(f"inputs[{i}] must be an object"); continue
            iid = item.get("id")
            if not isinstance(iid, str) or not ID_RE.fullmatch(iid): errors.append(f"inputs[{i}].id is invalid")
            elif iid in seen: errors.append(f"duplicate input id: {iid}")
            else: seen.add(iid)
            env = item.get("env")
            if not isinstance(env, str) or not env or not re.fullmatch(r"[A-Z][A-Z0-9_]*", env):
                errors.append(f"inputs[{i}].env must be an uppercase environment variable")
            digest = item.get("sha256")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                errors.append(f"inputs[{i}].sha256 must be null or 64 lowercase hex characters")
            if item.get("redistributable") not in (True, False):
                errors.append(f"inputs[{i}].redistributable must be boolean")
    for key in ("scripts", "reference", "validation"):
        value = doc.get("layout", {}).get(key) if isinstance(doc.get("layout"), dict) else None
        if value is not None:
            try: safe_rel(str(value))
            except ProfileError as exc: errors.append(f"layout.{key}: {exc}")
    if root is not None:
        for required in ("profile.json", "README.md", "scripts"):
            if not (root / required).exists(): errors.append(f"missing required profile path: {required}")
        # Private/proprietary target bytes are external by contract.  The SDK refuses
        # common binary-container suffixes unless explicitly whitelisted as redistributable.
        allow = set(doc.get("redistributable_files", [])) if isinstance(doc.get("redistributable_files"), list) else set()
        for path in root.rglob("*"):
            if not path.is_file() or any(part in SKIP_PARTS for part in path.parts): continue
            rel = path.relative_to(root).as_posix()
            if path.suffix.lower() in BINARY_SUFFIXES and rel not in allow:
                errors.append(f"binary-like file is not declared redistributable: {rel}")
    return errors

def skeleton(ident: str, name: str, description: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "profile_api": PROFILE_API_VERSION,
        "id": ident,
        "name": name,
        "description": description,
        "minimum_ppc_lab": DEFAULT_MINIMUM,
        "architecture": {"guest": "ppc32", "endian": "big"},
        "inputs": [{
            "id": "image", "env": "PPC_LAB_TARGET", "required": True,
            "redistributable": False, "sha256": None,
            "description": "External target image; never committed to the profile by default."
        }],
        "entry_points": [],
        "runtime": {"personality": None, "bindings": []},
        "layout": {"scripts": "scripts", "reference": "reference", "validation": "validation"},
        "redistributable_files": [],
        "tags": [],
        "notes": [],
    }

def cmd_init(ns: argparse.Namespace) -> int:
    root = ns.directory.resolve()
    if root.exists() and any(root.iterdir()) and not ns.force:
        raise ProfileError(f"directory is not empty: {root}; use --force to add/replace SDK files")
    root.mkdir(parents=True, exist_ok=True)
    for child in ("scripts", "reference", "validation"):
        (root / child).mkdir(exist_ok=True)
    doc = skeleton(ns.id, ns.name or ns.id, ns.description or "")
    write_json(root / "profile.json", doc)
    (root / "README.md").write_text(
        f"# {doc['name']} PPC Lab profile\n\n"
        f"Profile id: `{doc['id']}`. Target binaries stay external and are supplied through `PPC_LAB_TARGET`.\n\n"
        "## Validate\n\n```bash\nppc-lab-target validate .\n```\n\n"
        "## Run\n\n```bash\nexport PPC_LAB_TARGET=/absolute/path/to/target\n./scripts/run.sh\n```\n",
        encoding="utf-8",
    )
    run = root / "scripts" / "run.sh"
    run.write_text(
        "#!/usr/bin/env bash\n"
        "# SPDX-License-Identifier: GPL-3.0-only\n"
        "set -euo pipefail\n"
        ': "${PPC_LAB_TARGET:?set PPC_LAB_TARGET}"\n'
        'PPC_LAB_BIN="${PPC_LAB_BIN:-ppc-lab}"\n'
        'exec "$PPC_LAB_BIN" image-info "$PPC_LAB_TARGET"\n',
        encoding="utf-8",
    )
    run.chmod(0o755)
    for marker in (root / "reference" / ".gitkeep", root / "validation" / ".gitkeep"):
        marker.write_text("", encoding="utf-8")
    print(root)
    return 0

def cmd_validate(ns: argparse.Namespace) -> int:
    root = ns.directory.resolve()
    doc = read_json(root / "profile.json")
    errors = validate_doc(doc, root)
    result = {"schema": "ppc-lab-target-profile-validation-v1", "profile": str(root), "ok": not errors, "errors": errors}
    if ns.json: print(json.dumps(result, indent=2, sort_keys=True))
    elif errors:
        for e in errors: print(f"ERROR: {e}", file=sys.stderr)
    else: print(f"PASS: {doc['id']} target profile is valid")
    return 0 if not errors else 1

def cmd_inspect(ns: argparse.Namespace) -> int:
    root = ns.directory.resolve(); doc = read_json(root / "profile.json")
    errors = validate_doc(doc, root)
    result = {
        "schema": "ppc-lab-target-profile-inspection-v1", "ok": not errors,
        "id": doc.get("id"), "name": doc.get("name"), "minimum_ppc_lab": doc.get("minimum_ppc_lab"),
        "inputs": doc.get("inputs", []), "entry_points": doc.get("entry_points", []), "errors": errors,
    }
    if ns.json: print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"id={result['id']} name={result['name']} minimum_ppc_lab={result['minimum_ppc_lab']} valid={'yes' if result['ok'] else 'no'}")
        for item in result["inputs"]: print(f"input.{item.get('id')}={item.get('env')} redistributable={str(item.get('redistributable')).lower()}")
    return 0 if not errors else 1

def profile_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink(): continue
        rel = p.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts) or p.suffix == ".pyc": continue
        out.append(p)
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())

def zip_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    import datetime as dt
    t = max(epoch, 315532800)  # ZIP epoch starts at 1980-01-01 UTC.
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return d.year, d.month, d.day, d.hour, d.minute, d.second - d.second % 2

def cmd_pack(ns: argparse.Namespace) -> int:
    root = ns.directory.resolve(); doc = read_json(root / "profile.json")
    errors = validate_doc(doc, root)
    if errors: raise ProfileError("profile validation failed: " + "; ".join(errors))
    files = profile_files(root)
    manifest = {
        "schema": PACKAGE_SCHEMA, "profile_schema": SCHEMA, "profile_api": PROFILE_API_VERSION,
        "id": doc["id"], "minimum_ppc_lab": doc["minimum_ppc_lab"],
        "files": [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
    }
    out = ns.out.resolve(); out.parent.mkdir(parents=True, exist_ok=True)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", ns.epoch))
    ztime = zip_time(epoch)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        prefix = f"{doc['id']}/"
        for p in files:
            rel = prefix + p.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel, ztime); info.create_system = 3
            mode = 0o755 if os.access(p, os.X_OK) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        payload = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
        info = zipfile.ZipInfo(prefix + "PROFILE-PACKAGE.json", ztime); info.create_system = 3; info.external_attr = (stat.S_IFREG | 0o644) << 16
        zf.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    print(f"{out} sha256={sha256_file(out)}")
    return 0

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create a target-profile skeleton"); p.add_argument("directory", type=Path); p.add_argument("--id", required=True); p.add_argument("--name"); p.add_argument("--description"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("validate", help="validate a target profile"); p.add_argument("directory", type=Path); p.add_argument("--json", action="store_true")
    p = sub.add_parser("inspect", help="summarize a target profile"); p.add_argument("directory", type=Path); p.add_argument("--json", action="store_true")
    p = sub.add_parser("pack", help="create a deterministic redistributable profile ZIP"); p.add_argument("directory", type=Path); p.add_argument("--out", type=Path, required=True); p.add_argument("--epoch", type=int, default=946684800)
    ns = ap.parse_args()
    try:
        if ns.cmd == "init": return cmd_init(ns)
        if ns.cmd == "validate": return cmd_validate(ns)
        if ns.cmd == "inspect": return cmd_inspect(ns)
        return cmd_pack(ns)
    except (ProfileError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ppc-lab-target: {exc}", file=sys.stderr); return 2

if __name__ == "__main__":
    raise SystemExit(main())
