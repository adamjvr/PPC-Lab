#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile


def run(*args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if p.returncode != 0:
        raise AssertionError(
            f"command failed ({p.returncode}): {' '.join(args)}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}"
        )
    return p


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: test_install_contract.py CMAKE BUILD_DIR", file=sys.stderr)
        return 2
    cmake = sys.argv[1]
    build = pathlib.Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory(prefix="ppclab-install-") as td:
        root = pathlib.Path(td)
        prefix = root / "prefix"
        cache = (build / "CMakeCache.txt").read_text(encoding="utf-8", errors="replace") if (build / "CMakeCache.txt").is_file() else ""
        config = "Release"
        for line in cache.splitlines():
            if line.startswith("CMAKE_BUILD_TYPE:STRING=") and line.split("=", 1)[1]:
                config = line.split("=", 1)[1]
                break
        multi_config = any(
            line.startswith("CMAKE_CONFIGURATION_TYPES:") and line.split("=", 1)[1]
            for line in cache.splitlines()
        )
        install_args = [cmake, "--install", str(build), "--prefix", str(prefix)]
        if multi_config:
            install_args.extend(["--config", config])
        run(*install_args)

        exe_name = "ppc-lab.exe" if os.name == "nt" else "ppc-lab"
        exe = prefix / "bin" / exe_name
        assert exe.is_file(), exe
        assert (prefix / "include" / "ppclab" / "ppc" / "UniversalImage.hpp").is_file()
        version_header = prefix / "include" / "ppclab" / "Version.hpp"
        assert version_header.is_file(), version_header
        version_text = version_header.read_text(encoding="utf-8")
        assert '#define PPCLAB_VERSION_STRING "3.9.1"' in version_text
        assert '#define PPCLAB_CPP_API_VERSION 1' in version_text
        assert '#define PPCLAB_CPP_ABI_VERSION 1' in version_text
        worker = prefix / "bin" / "ppc-lab-worker"
        assert worker.is_file(), worker
        orchestrator = prefix / "bin" / "ppc-lab-orchestrate"
        assert orchestrator.is_file(), orchestrator
        fleet = prefix / "bin" / "ppc-lab-fleet"
        assert fleet.is_file(), fleet
        evidence = prefix / "bin" / "ppc-lab-evidence"
        assert evidence.is_file(), evidence
        api = prefix / "bin" / "ppc-lab-api"
        assert api.is_file(), api
        corpus = prefix / "bin" / "ppc-lab-corpus"
        assert corpus.is_file(), corpus
        triage = prefix / "bin" / "ppc-lab-triage"
        assert triage.is_file(), triage
        explorer = prefix / "bin" / "ppc-lab-explore"
        assert explorer.is_file(), explorer
        prioritizer = prefix / "bin" / "ppc-lab-prioritize"
        assert prioritizer.is_file(), prioritizer
        campaign = prefix / "bin" / "ppc-lab-campaign"
        assert campaign.is_file(), campaign
        scheduler = prefix / "bin" / "ppc-lab-schedule"
        assert scheduler.is_file(), scheduler
        control = prefix / "bin" / "ppc-lab-control"
        assert control.is_file(), control
        knowledge = prefix / "bin" / "ppc-lab-knowledge"
        assert knowledge.is_file(), knowledge
        hypothesize = prefix / "bin" / "ppc-lab-hypothesize"
        platform = prefix / "bin" / "ppc-lab-platform"
        assert hypothesize.is_file(), hypothesize
        assert platform.is_file(), platform
        target_sdk = prefix / "bin" / "ppc-lab-target"
        release_tool = prefix / "bin" / "ppc-lab-release"
        compat_tool = prefix / "bin" / "ppc-lab-compat"
        assert target_sdk.is_file(), target_sdk
        assert release_tool.is_file(), release_tool
        assert compat_tool.is_file(), compat_tool
        support_tool = prefix / "bin" / "ppc-lab-support"
        assert support_tool.is_file(), support_tool
        deploy_tool = prefix / "bin" / "ppc-lab-deploy"
        assert deploy_tool.is_file(), deploy_tool
        backup_tool = prefix / "bin" / "ppc-lab-backup"
        assert backup_tool.is_file(), backup_tool
        observe_tool = prefix / "bin" / "ppc-lab-observe"
        security_tool = prefix / "bin" / "ppc-lab-security"
        replicate_tool = prefix / "bin" / "ppc-lab-replicate"
        assert security_tool.is_file()
        assert replicate_tool.is_file()
        assert observe_tool.is_file(), observe_tool
        assert '#define PPCLAB_OBSERVABILITY_API_VERSION 1' in version_text
        for name in ["ppc-lab-trace-capture","ppc-lab-trace-analyze","ppc-lab-trace-diff","ppc_trace_intelligence.py"]:
            assert (prefix / "bin" / name).is_file(), name
        schema_candidates = list(prefix.glob("share/ppc-lab/schemas/ppc-lab-job-v1.schema.json"))
        assert schema_candidates, "worker job schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-orchestration-v1.schema.json")), "orchestration schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-orchestration-job-result-v1.schema.json")), "orchestration job-result schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-fleet-v1.schema.json")), "fleet manifest schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-fleet-job-result-v1.schema.json")), "fleet job-result schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-fleet-summary-v1.schema.json")), "fleet summary schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-evidence-query-v1.schema.json")), "evidence query schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-evidence-report-v1.schema.json")), "evidence report schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-evidence-verify-v1.schema.json")), "evidence verify schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-api-ready-v1.schema.json")), "API ready schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-api-health-v1.schema.json")), "API health schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-api-discovery-v1.schema.json")), "API discovery schema was not installed"
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-trace-analysis-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-trace-diff-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-corpus-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-corpus-case-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-corpus-replay-summary-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-differential-triage-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-triage-bundle-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-exploration-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-exploration-case-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-exploration-summary-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-priority-policy-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-priority-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-campaign-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-campaign-state-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-campaign-summary-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-campaign-triage-summary-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-scheduler-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-scheduler-state-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-scheduler-summary-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-control-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-control-item-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-control-telemetry-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-control-history-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-control-history-record-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-knowledge-query-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-knowledge-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-knowledge-related-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-knowledge-path-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-knowledge-verify-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-hypothesis-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-hypothesis-experiment-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-hypothesis-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-platform-status-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-upgrade-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-acceptance-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-target-profile-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-target-profile-package-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-release-manifest-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-compatibility-snapshot-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-support-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-support-bundle-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-deployment-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-deployment-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-backup-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-backup-report-v1.schema.json"))
        assert (prefix / "bin" / "ppc-lab-upgrade").is_file()
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-upgrade-plan-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-upgrade-transaction-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-release-channel-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-observability-store-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-observation-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-observability-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-observability-policy-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-observability-check-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-capacity-report-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-auth-store-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-audit-record-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-replication-store-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-replication-bundle-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-replication-receipt-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-replication-status-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/schemas/ppc-lab-replication-verify-v1.schema.json"))
        assert list(prefix.glob("share/ppc-lab/channels/release-channels.json"))
        assert list(prefix.glob("share/ppc-lab/compat/baselines/v3.1.0.json"))
        config_candidates = list(prefix.glob("lib*/cmake/PPCLab/PPCLabConfig.cmake"))
        assert config_candidates, "PPCLabConfig.cmake was not installed"

        version = run(str(exe), "--version")
        assert version.stdout.strip() == "PPC Lab 3.9.1"
        caps = run(str(exe), "capabilities", "--json")
        assert '"schema": "ppc-lab-capabilities-v1"' in caps.stdout
        assert '"orchestration": "ppc-lab-orchestration-v1"' in caps.stdout
        assert '"fleet": "ppc-lab-fleet-v1"' in caps.stdout
        assert '"evidence_query": "ppc-lab-evidence-query-v1"' in caps.stdout
        assert '"http_api": "ppc-lab-http-api-v1"' in caps.stdout
        assert '"trace_analysis": "ppc-lab-trace-analysis-v1"' in caps.stdout
        assert '"trace_diff": "ppc-lab-trace-diff-v1"' in caps.stdout
        assert '"corpus_case": "ppc-lab-corpus-case-v1"' in caps.stdout
        assert '"corpus_replay": "ppc-lab-corpus-replay-summary-v1"' in caps.stdout
        assert '"differential_triage": "ppc-lab-differential-triage-v1"' in caps.stdout
        assert '"triage_bundle": "ppc-lab-triage-bundle-v1"' in caps.stdout
        assert '"exploration": "ppc-lab-exploration-v1"' in caps.stdout
        assert '"exploration_case": "ppc-lab-exploration-case-v1"' in caps.stdout
        assert '"exploration_summary": "ppc-lab-exploration-summary-v1"' in caps.stdout
        assert '"campaign": "ppc-lab-campaign-v1"' in caps.stdout
        assert '"campaign_state": "ppc-lab-campaign-state-v1"' in caps.stdout
        assert '"campaign_summary": "ppc-lab-campaign-summary-v1"' in caps.stdout
        assert '"campaign_triage_summary": "ppc-lab-campaign-triage-summary-v1"' in caps.stdout
        assert '"priority_policy": "ppc-lab-priority-policy-v1"' in caps.stdout
        assert '"priority_report": "ppc-lab-priority-report-v1"' in caps.stdout
        assert '"control": "ppc-lab-control-v1"' in caps.stdout
        assert '"control_telemetry": "ppc-lab-control-telemetry-v1"' in caps.stdout
        assert '"knowledge_query": "ppc-lab-knowledge-query-v1"' in caps.stdout
        assert '"hypothesis_report": "ppc-lab-hypothesis-report-v1"' in caps.stdout
        assert '"hypothesis_experiment": "ppc-lab-hypothesis-experiment-v1"' in caps.stdout
        assert '"hypothesis": "ppc-lab-hypothesis-v1"' in caps.stdout
        assert '"platform_status": "ppc-lab-platform-status-v1"' in caps.stdout
        assert '"upgrade_report": "ppc-lab-upgrade-report-v1"' in caps.stdout
        assert '"acceptance_report": "ppc-lab-acceptance-report-v1"' in caps.stdout
        assert '"target_profile": "ppc-lab-target-profile-v1"' in caps.stdout
        assert '"target_profile_package": "ppc-lab-target-profile-package-v1"' in caps.stdout
        assert '"release_manifest": "ppc-lab-release-manifest-v1"' in caps.stdout
        assert '"api": {"cpp": 1, "abi": 1, "target_profile": 1, "release": 1, "compatibility": 1, "observability": 1, "security": 1, "replication": 1}' in caps.stdout
        assert '"compatibility_snapshot": "ppc-lab-compatibility-snapshot-v1"' in caps.stdout
        assert '"support_report": "ppc-lab-support-report-v1"' in caps.stdout
        assert '"support_bundle": "ppc-lab-support-bundle-v1"' in caps.stdout
        assert '"deployment": "ppc-lab-deployment-v1"' in caps.stdout
        assert '"deployment_report": "ppc-lab-deployment-report-v1"' in caps.stdout
        assert '"backup": "ppc-lab-backup-v1"' in caps.stdout
        assert '"backup_report": "ppc-lab-backup-report-v1"' in caps.stdout
        assert '"upgrade_plan": "ppc-lab-upgrade-plan-v1"' in caps.stdout
        assert '"upgrade_transaction": "ppc-lab-upgrade-transaction-v1"' in caps.stdout
        assert '"release_channel": "ppc-lab-release-channel-v1"' in caps.stdout
        assert '"observation": "ppc-lab-observation-v1"' in caps.stdout
        assert '"observability_report": "ppc-lab-observability-report-v1"' in caps.stdout
        assert '"capacity_report": "ppc-lab-capacity-report-v1"' in caps.stdout
        assert '"auth_store": "ppc-lab-auth-store-v1"' in caps.stdout
        assert '"audit_record": "ppc-lab-audit-record-v1"' in caps.stdout
        assert '"replication_bundle": "ppc-lab-replication-bundle-v1"' in caps.stdout
        assert '"replication_receipt": "ppc-lab-replication-receipt-v1"' in caps.stdout

        consumer = root / "consumer"
        consumer.mkdir()
        (consumer / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(PPCLabConsumer LANGUAGES CXX)\n"
            "find_package(PPCLab 3.6 CONFIG REQUIRED)\n"
            "add_executable(consumer main.cpp)\n"
            "target_link_libraries(consumer PRIVATE PPCLab::core)\n",
            encoding="utf-8",
        )
        (consumer / "main.cpp").write_text(
            '#include "ppclab/ppc/UniversalImage.hpp"\n'
            '#include "ppclab/Version.hpp"\n'
            "static_assert(PPCLAB_CPP_API_VERSION == 1);\n"
            "static_assert(PPCLAB_CPP_ABI_VERSION == 1);\n"
            "int main() { return ppclab::ppc::UniversalImageLoader::formatName("
            "ppclab::ppc::UniversalImageFormat::Elf32PpcBe)[0] == 'E' ? 0 : 1; }\n",
            encoding="utf-8",
        )
        consumer_build = root / "consumer-build"
        run(cmake, "-S", str(consumer), "-B", str(consumer_build), f"-DCMAKE_PREFIX_PATH={prefix}", f"-DCMAKE_BUILD_TYPE={config}")
        run(cmake, "--build", str(consumer_build), "--config", config)

    print("PASS: install tree and downstream find_package(PPCLab) contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
