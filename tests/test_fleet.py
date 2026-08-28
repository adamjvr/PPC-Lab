#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.argv[1]).resolve()
FLEET = ROOT / "scripts" / "ppc_lab_fleet.py"
WORKER = ROOT / "scripts" / "ppc_lab_worker.py"
EVIDENCE = ROOT / "scripts" / "ppc_lab_evidence.py"


def invoke(manifest: Path, out: Path, cache: Path, local_root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FLEET), str(manifest), "--out", str(out), "--cache", str(cache),
         "--local-root", str(local_root), *extra],
        text=True, capture_output=True, check=False,
    )


with tempfile.TemporaryDirectory(prefix="ppclab-fleet-test-") as td_text:
    td = Path(td_text)
    code = td / "leaf.bin"
    code.write_bytes(struct.pack(">II", 0x3860002A, 0x4E800020))  # li r3,42 ; blr
    host_a = td / "host-a"
    host_b = td / "host-b"
    host_flaky = td / "host-flaky"
    host_a.mkdir(); host_b.mkdir(); host_flaky.mkdir()
    flaky_worker = td / "flaky-worker"
    flaky_worker.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    flaky_worker.chmod(0o755)

    def job(job_id: str) -> dict:
        return {
            "schema": "ppc-lab-job-v1",
            "id": job_id,
            "image": {"path": "leaf.bin", "kind": "raw", "code_base": "0x10000000"},
            "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100},
        }

    hosts = [
        {"name": "a", "transport": "local", "slots": 1, "root": str(host_a),
         "ppc_lab": str(CLI), "worker": str(WORKER), "python": sys.executable, "tags": ["cpu"]},
        {"name": "b", "transport": "local", "slots": 1, "root": str(host_b),
         "ppc_lab": str(CLI), "worker": str(WORKER), "python": sys.executable, "tags": ["cpu"]},
        {"name": "flaky", "transport": "local", "slots": 1, "root": str(host_flaky),
         "ppc_lab": str(CLI), "worker": str(flaky_worker), "python": sys.executable, "tags": ["cpu"]},
        {"name": "dead", "transport": "local", "slots": 1, "root": str(td / "dead"),
         "ppc_lab": str(td / "missing-ppc-lab"), "worker": str(WORKER), "python": sys.executable},
    ]
    manifest = td / "fleet.json"
    manifest.write_text(json.dumps({
        "schema": "ppc-lab-fleet-v1", "timeout": 10, "retries": 1,
        "hosts": hosts,
        "jobs": [
            {"name": "one", "job": job("one"), "requires_tags": ["cpu"]},
            {"name": "two", "job": job("two"), "requires_tags": ["cpu"]},
            {"name": "three", "job": job("three"), "requires_tags": ["cpu"]},
            {"name": "four", "job": job("four"), "requires_tags": ["cpu"]},
        ]
    }), encoding="utf-8")

    out = td / "out"
    cache = td / "cache"
    evidence_store = td / "evidence-store"
    first = invoke(manifest, out, cache, td, "--evidence-store", str(evidence_store))
    assert first.returncode == 0, (first.stdout, first.stderr)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == "ppc-lab-fleet-summary-v1"
    assert summary["evidence_store"] == str(evidence_store.resolve())
    evidence_query = subprocess.run([sys.executable, str(EVIDENCE), "query", str(evidence_store), "--schema", "ppc-lab-fleet-job-result-v1", "--json"], text=True, capture_output=True, check=False)
    assert evidence_query.returncode == 0, (evidence_query.stdout, evidence_query.stderr)
    assert json.loads(evidence_query.stdout)["count"] == 4
    assert summary["executed"] == 4 and summary["failed"] == 0
    assert summary["resumed"] == 0 and summary["cache_hits"] == 0
    health = {row["name"]: row for row in summary["hosts"]}
    assert health["a"]["healthy"] is True and health["b"]["healthy"] is True
    assert health["flaky"]["healthy"] is True and health["dead"]["healthy"] is False
    used = {row["host"] for row in summary["results"]}
    assert used.issubset({"a", "b"}) and used, used
    records = []
    for row in summary["results"]:
        record = json.loads((out / row["file"]).read_text())
        records.append(record)
        assert record["schema"] == "ppc-lab-fleet-job-result-v1"
        assert record["response"]["result"]["registers"]["r3"] == "0x0000002a"
        assert record["attempts"]
    assert any(len(record["attempts"]) == 2 and record["attempts"][0]["host"] == "flaky" and record["attempts"][1]["host"] in {"a", "b"} for record in records), records

    # Exact result-directory resume should not execute anything.
    resumed = invoke(manifest, out, cache, td)
    assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
    resumed_summary = json.loads((out / "summary.json").read_text())
    assert resumed_summary["resumed"] == 4 and resumed_summary["executed"] == 0

    # Ignoring result-directory resume should reuse the shared content cache.
    cached_out = td / "cached-out"
    cached = invoke(manifest, cached_out, cache, td, "--no-resume")
    assert cached.returncode == 0, (cached.stdout, cached.stderr)
    cached_summary = json.loads((cached_out / "summary.json").read_text())
    assert cached_summary["cache_hits"] == 4 and cached_summary["executed"] == 0

    # Binary byte changes invalidate the fleet cache even with identical job JSON/path.
    code.write_bytes(struct.pack(">II", 0x3860002B, 0x4E800020))  # li r3,43 ; blr
    changed_out = td / "changed-out"
    changed = invoke(manifest, changed_out, cache, td, "--no-resume")
    assert changed.returncode == 0, (changed.stdout, changed.stderr)
    changed_summary = json.loads((changed_out / "summary.json").read_text())
    assert changed_summary["executed"] == 4 and changed_summary["cache_hits"] == 0
    for row in changed_summary["results"]:
        record = json.loads((changed_out / row["file"]).read_text())
        assert record["response"]["result"]["registers"]["r3"] == "0x0000002b"

    # Exercise the actual SSH/scp transport code with local fake OpenSSH executables.
    fake_ssh = td / "fake-ssh"
    fake_ssh.write_text("""#!/usr/bin/env python3
import subprocess, sys
args=sys.argv[1:]
i=0
while i < len(args) and args[i] == '-o':
    i += 2
if i >= len(args):
    raise SystemExit(2)
i += 1  # endpoint
if i >= len(args):
    raise SystemExit(2)
command=args[i]
raise SystemExit(subprocess.run(command, shell=True).returncode)
""", encoding="utf-8")
    fake_ssh.chmod(0o755)
    fake_scp = td / "fake-scp"
    fake_scp.write_text("""#!/usr/bin/env python3
import pathlib, shlex, shutil, sys
args=sys.argv[1:]
i=0
while i < len(args) and args[i] == '-o':
    i += 2
args=args[i:]
if len(args) != 2 or ':' not in args[1]:
    raise SystemExit(2)
source=pathlib.Path(args[0])
remote_text=args[1].split(':',1)[1]
parts=shlex.split(remote_text)
if len(parts) != 1:
    raise SystemExit(2)
dest=pathlib.Path(parts[0])
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(source,dest)
""", encoding="utf-8")
    fake_scp.chmod(0o755)
    ssh_root = td / "ssh-host"
    ssh_root.mkdir()
    ssh_manifest = td / "ssh-fleet.json"
    ssh_manifest.write_text(json.dumps({
        "schema": "ppc-lab-fleet-v1",
        "hosts": [{"name": "ssh-a", "transport": "ssh", "endpoint": "fake@ssh-a", "slots": 1,
                   "root": str(ssh_root), "ppc_lab": str(CLI), "worker": str(WORKER), "python": sys.executable}],
        "jobs": [{"name": "ssh-job", "job": job("ssh-job")}]
    }), encoding="utf-8")
    ssh_out = td / "ssh-out"
    ssh_run = invoke(ssh_manifest, ssh_out, cache, td, "--ssh", str(fake_ssh), "--scp", str(fake_scp), "--no-resume")
    assert ssh_run.returncode == 0, (ssh_run.stdout, ssh_run.stderr)
    ssh_summary = json.loads((ssh_out / "summary.json").read_text())
    assert ssh_summary["executed"] == 1 and ssh_summary["results"][0]["host"] == "ssh-a"
    ssh_record = json.loads((ssh_out / ssh_summary["results"][0]["file"]).read_text())
    assert ssh_record["response"]["result"]["registers"]["r3"] == "0x0000002b"
    staged = ssh_root / ".ppc-lab" / "store" / ssh_record["inputs"]["image.path"]["sha256"]
    assert staged.is_file() and staged.read_bytes() == code.read_bytes()

    # Failed guest executions are resumable evidence but never shared-cache hits.
    failed_job = job("failed")
    failed_job["execution"] = dict(failed_job["execution"], max_instructions=1)
    failed_manifest = td / "failed.json"
    failed_manifest.write_text(json.dumps({
        "schema": "ppc-lab-fleet-v1", "hosts": hosts[:2], "jobs": [{"name": "failed", "job": failed_job}]
    }), encoding="utf-8")
    failed_out = td / "failed-out"
    failed_first = invoke(failed_manifest, failed_out, cache, td)
    assert failed_first.returncode == 1, (failed_first.stdout, failed_first.stderr)
    failed_summary = json.loads((failed_out / "summary.json").read_text())
    assert failed_summary["failed"] == 1 and failed_summary["executed"] == 1
    failed_resume = invoke(failed_manifest, failed_out, cache, td)
    assert failed_resume.returncode == 1
    failed_resume_summary = json.loads((failed_out / "summary.json").read_text())
    assert failed_resume_summary["failed"] == 1 and failed_resume_summary["resumed"] == 1
    failed_cache_out = td / "failed-cache-out"
    failed_again = invoke(failed_manifest, failed_cache_out, cache, td, "--no-resume")
    assert failed_again.returncode == 1
    failed_again_summary = json.loads((failed_cache_out / "summary.json").read_text())
    assert failed_again_summary["executed"] == 1 and failed_again_summary["cache_hits"] == 0

    # Required tags are enforced before scheduling.
    no_host_manifest = td / "no-host.json"
    no_host_manifest.write_text(json.dumps({
        "schema": "ppc-lab-fleet-v1", "hosts": hosts[:2],
        "jobs": [{"name": "gpu-only", "job": job("gpu"), "requires_tags": ["gpu"]}]
    }), encoding="utf-8")
    no_host = invoke(no_host_manifest, td / "no-host-out", cache, td)
    assert no_host.returncode == 2
    assert "no compatible host" in no_host.stderr

    # Source containment is checked before staging to any fleet host.
    outside = td.parent / (td.name + "-outside.bin")
    outside.write_bytes(b"outside")
    try:
        escaped_job = job("escape")
        escaped_job["image"] = {"path": str(outside), "kind": "raw"}
        escape_manifest = td / "escape.json"
        escape_manifest.write_text(json.dumps({
            "schema": "ppc-lab-fleet-v1", "hosts": hosts[:1], "jobs": [{"job": escaped_job}]
        }), encoding="utf-8")
        escaped = invoke(escape_manifest, td / "escape-out", cache, td)
        assert escaped.returncode == 2
        assert "outside local root" in escaped.stderr
    finally:
        outside.unlink(missing_ok=True)

print("PASS: PPC Lab distributed local-fleet scheduling/cache/health")
