#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPL = ROOT / "scripts" / "ppc_lab_replicate.py"
EVID = ROOT / "scripts" / "ppc_lab_evidence.py"
KNOW = ROOT / "scripts" / "ppc_lab_knowledge.py"
CTRL = ROOT / "scripts" / "ppc_lab_control.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rewrite_manifest(src: Path, dst: Path, repl, *, mutate_member: bool = False) -> None:
    with zipfile.ZipFile(src) as zin:
        payloads = {n: zin.read(n) for n in zin.namelist()}
    manifest = json.loads(payloads["bundle.json"])
    manifest["created_at"] = "2030-01-01T00:00:00Z"
    manifest["bundle_id"] = repl.sha256_bytes(repl.manifest_material(manifest))
    payloads["bundle.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if mutate_member:
        member = next(n for n in payloads if n.startswith("evidence/"))
        payloads[member] += b" "
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name in sorted(payloads):
            zout.writestr(name, payloads[name])


def main() -> int:
    repl = load(REPL, "ppclab_test_repl")
    evid = load(EVID, "ppclab_test_evid")
    know = load(KNOW, "ppclab_test_know")
    ctrl = load(CTRL, "ppclab_test_ctrl")
    with tempfile.TemporaryDirectory(prefix="ppclab-replication-") as raw:
        td = Path(raw)
        source_rep = td / "site-a-rep"
        dest_rep = td / "site-b-rep"
        _, source_state = repl.ensure_store(source_rep, create=True, site="site-a")
        _, dest_state = repl.ensure_store(dest_rep, create=True, site="site-b")
        assert source_state["next_generation"] == 1 and dest_state["next_generation"] == 1

        source_e = td / "source-evidence"; evid.init_store(source_e)
        source_k = td / "source-knowledge"; know.init_graph(source_k)
        source_c = td / "source-control"; ctrl.ensure_root(source_c, create=True)
        private = td / "private-target.elf"; private.write_bytes(b"PRIVATE-PPC-TARGET-BYTES-DO-NOT-REPLICATE")
        target_sha = repl.sha256_file(private)
        doc = {
            "schema": "ppc-lab-fleet-job-result-v1",
            "name": "replication-fixture",
            "engine_version": "3.9.0",
            "host": "site-a-worker",
            "inputs": {"image.path": {"logical_path": "private-target.elf", "sha256": target_sha, "size": private.stat().st_size}},
            "response": {"schema": "ppc-lab-worker-response-v1", "id": "rep-1", "ok": True, "exit_code": 0, "engine_version": "3.9.0",
                         "result": {"schema": "ppc-lab-result-v1", "backend": "builtin-ppc32be", "stop_reason": "return", "instructions": 2,
                                    "pc": "0x10000004", "registers": {"r3": "0x0000002a"}, "dumps": []}},
        }
        artifact = td / "artifact.json"; artifact.write_text(json.dumps(doc) + "\n")
        er = evid.ingest(source_e, [artifact], strict=True); assert er["added"] == 1
        kr = know.ingest_paths(source_k, [artifact]); assert kr["added"] == 1
        hist = source_c / "history" / "history.ndjson"
        hist.write_text(json.dumps({"schema": "ppc-lab-control-history-record-v1", "id": "finished-1", "status": "complete",
                                    "manifest": str(private), "run_out": str(td / "runs"), "project": "fixture"}) + "\n")

        bundle = td / "site-a-1.zip"
        manifest = repl.build_bundle(source_rep, source_state, bundle, source_e, source_k, source_c)
        assert manifest["source_site"] == "site-a" and manifest["generation"] == 1
        assert manifest["policy"]["target_binaries_included"] is False
        verified, errors = repl.verify_bundle(bundle); assert not errors, errors
        assert verified["bundle_id"] == manifest["bundle_id"]
        raw_bundle = bundle.read_bytes()
        assert b"PRIVATE-PPC-TARGET-BYTES-DO-NOT-REPLICATE" not in raw_bundle
        with zipfile.ZipFile(bundle) as zf:
            names = set(zf.namelist())
            assert "control/history.ndjson" in names and "control.json" not in names
            assert not any(n.endswith((".elf", ".bin", ".exe")) for n in names)
            assert str(private).encode() not in zf.read("control/history.ndjson")

        dest_e = td / "dest-evidence"; dest_k = td / "dest-knowledge"
        receipt = repl.import_bundle(dest_rep, bundle, dest_e, dest_k)
        assert receipt["status"] == "imported" and receipt["evidence"]["ingested"] == 1 and receipt["knowledge"]["ingested"] == 1
        # Content-addressed merge is idempotent.
        again = repl.import_bundle(dest_rep, bundle, dest_e, dest_k); assert again["status"] == "already-imported"
        assert evid.verify(dest_e)["ok"] is True
        assert know.verify_graph(dest_k)["ok"] is True
        with sqlite3.connect(dest_e / "evidence.sqlite3") as conn:
            assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1
        with sqlite3.connect(dest_k / "knowledge.sqlite3") as conn:
            assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1

        status = repl.status(dest_rep, repl.ensure_store(dest_rep)[1])
        assert status["imported_receipts"] == 1 and status["latest_generation_by_site"]["site-a"] == 1
        assert (dest_rep / "control-history" / "site-a" / "00000000000000000001.ndjson").is_file()

        # A different valid bundle claiming the same site/generation is a conflict.
        conflict = td / "conflict.zip"; rewrite_manifest(bundle, conflict, repl)
        m2, e2 = repl.verify_bundle(conflict); assert not e2 and m2["bundle_id"] != manifest["bundle_id"]
        try:
            repl.import_bundle(dest_rep, conflict, dest_e, dest_k)
            raise AssertionError("conflicting site generation was accepted")
        except repl.ReplicationError as exc:
            assert "conflict" in str(exc)

        # Member tampering is detected independently of ZIP transport integrity.
        tampered = td / "tampered.zip"; rewrite_manifest(bundle, tampered, repl, mutate_member=True)
        _, terr = repl.verify_bundle(tampered); assert any("mismatch" in x for x in terr)

        # A second export advances the local generation monotonically.
        _, source_state2 = repl.ensure_store(source_rep)
        bundle2 = td / "site-a-2.zip"; man2 = repl.build_bundle(source_rep, source_state2, bundle2, source_e, source_k, None)
        assert man2["generation"] == 2 and repl.ensure_store(source_rep)[1]["next_generation"] == 3

    print("PASS: multi-site content-addressed replication, receipts, conflicts, tamper detection, and private-target exclusion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
