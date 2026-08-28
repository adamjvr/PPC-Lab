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
        run(cmake, "--install", str(build), "--prefix", str(prefix), "--config", config)

        exe_name = "ppc-lab.exe" if os.name == "nt" else "ppc-lab"
        exe = prefix / "bin" / exe_name
        assert exe.is_file(), exe
        assert (prefix / "include" / "ppclab" / "ppc" / "UniversalImage.hpp").is_file()
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
        config_candidates = list(prefix.glob("lib*/cmake/PPCLab/PPCLabConfig.cmake"))
        assert config_candidates, "PPCLabConfig.cmake was not installed"

        version = run(str(exe), "--version")
        assert version.stdout.strip() == "PPC Lab 1.7.0"
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

        consumer = root / "consumer"
        consumer.mkdir()
        (consumer / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(PPCLabConsumer LANGUAGES CXX)\n"
            "find_package(PPCLab 1.0 CONFIG REQUIRED)\n"
            "add_executable(consumer main.cpp)\n"
            "target_link_libraries(consumer PRIVATE PPCLab::core)\n",
            encoding="utf-8",
        )
        (consumer / "main.cpp").write_text(
            '#include "ppclab/ppc/UniversalImage.hpp"\n'
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
