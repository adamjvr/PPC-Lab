# Installation and CMake consumption

PPC Lab can be used as a repository-local research tool or installed as a CLI plus C++ package. No mandatory third-party runtime dependency is required for the built-in PPC32-BE backend.

## Build and test

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
```

On multi-config generators such as Visual Studio, pass `--config Release` to build/test/install commands.

## Install to a prefix

```bash
cmake --install build/release --prefix "$HOME/.local"
```

The install tree contains:

- `bin/ppc-lab`;
- `bin/ppc-lab-worker`, `bin/ppc-lab-orchestrate`, `bin/ppc-lab-fleet`, and `bin/ppc-lab-campaign`;
- the static PPC Lab core library;
- `include/ppclab/ppc/*.hpp`;
- `PPCLabConfig.cmake`, `PPCLabConfigVersion.cmake`, and exported targets;
- README, changelog, license, and detailed docs.

## Consume from CMake

```cmake
cmake_minimum_required(VERSION 3.20)
project(MyResearchTool LANGUAGES CXX)
find_package(PPCLab 3.0 CONFIG REQUIRED)
add_executable(my-tool main.cpp)
target_link_libraries(my-tool PRIVATE PPCLab::core)
```

The exported core target propagates the required C++20 language feature and installed include path. Do not hard-code the PPC Lab source-tree include directory.

## Release contract test

`tests/test_install_contract.py` installs the current build into a temporary prefix, executes the installed CLI, discovers the package through `find_package(PPCLab CONFIG)`, and compiles a separate downstream consumer. This test exists specifically to catch packaging/export mistakes that ordinary in-tree tests cannot see.

## Server-tool installation

The same install step places `ppc-lab-worker`, `ppc-lab-orchestrate`, and `ppc-lab-fleet` in the install `bin` directory and the v1 JSON schemas under `share/ppc-lab/schemas/`. These tools use only Python's standard library. Fleet SSH transport additionally expects ordinary OpenSSH `ssh`/`scp` commands on the controller.

The worker locates `ppc-lab` through `--ppc-lab`, `PPC_LAB_BIN`, or `PATH`. A normal fleet host therefore needs the installed `bin` directory on the noninteractive SSH `PATH`; see `docs/FLEET.md`.

## Installed operational tools

The install tree also provides `ppc-lab-worker`, `ppc-lab-orchestrate`, `ppc-lab-fleet`, `ppc-lab-evidence`, `ppc-lab-corpus`, `ppc-lab-triage`, `ppc-lab-explore`, and `ppc-lab-campaign`. These are dependency-free Python entry points around the stable execution/result contracts; the evidence tool uses Python's bundled `sqlite3` module and requires no database service. JSON schemas are installed under `share/ppc-lab/schemas`.


## Behavioral corpus tool

`cmake --install` also installs `ppc-lab-corpus` and the v1 corpus schemas. The corpus command uses only Python's standard library and invokes the installed worker/CLI by default, so a normal PPC Lab install is sufficient for promote/replay/verify workflows. Private target binaries are not installed or copied by this tool unless embedding is explicitly requested.

### Autonomous campaign tool

`cmake --install` installs `ppc-lab-campaign` plus its v1 manifest/state/summary schemas. The campaign driver uses only Python's standard library and composes the installed PPC Lab worker/explorer/corpus/triage/evidence tools. No queue server, database service, or web framework is required.

A server install can therefore run:

```bash
ppc-lab-campaign /srv/research/campaign.json --out /srv/research/runs/001
```

Long-lived corpus/evidence directories may be outside the run directory. Target binary input paths remain subject to the campaign/worker root boundary.

PPC Lab v2.1 also installs `ppc-lab-prioritize` plus `ppc-lab-priority-policy-v1` and `ppc-lab-priority-report-v1` schemas. The tool uses only Python's standard library.

## Campaign control plane

A normal v2.3 install also installs `ppc-lab-control` beside `ppc-lab-schedule`. No extra Python packages, database, broker, or service framework are required. The four control-plane JSON schemas are installed under the normal `share/ppc-lab/schemas` directory. `ppc-lab-control serve` is a foreground process so deployments can use their existing OS/container supervisor rather than a PPC-Lab-specific daemon installer.

## Research knowledge graph

A normal v2.4 install adds `ppc-lab-knowledge` and the five v2.4 knowledge query/report/traversal/verification schemas. The tool uses Python's bundled `sqlite3` module; no graph database, broker, or service is required. The graph can index installed-server evidence directories or synchronize an existing `ppc-lab-evidence` store while leaving target binaries in their original private storage.


## Automated hypothesis engine

A normal v2.5 install adds `ppc-lab-hypothesize` plus the hypothesis report/experiment/promoted-record schemas. It uses only Python's standard library and consumes normal exploration JSON. Follow-up experiments are ordinary `ppc-lab-exploration-v1` manifests, so no additional execution daemon or dependency is required.

## v3.7 observability companion

The installed command set includes `ppc-lab-observe`. It is a standard-library operational companion and requires no metrics daemon, Prometheus client, or database package. Point it at the persistent `ppc-lab-control` root and a writable observability store. See [`OBSERVABILITY.md`](OBSERVABILITY.md).
## v3.9 replication companion

`cmake --install` installs `ppc-lab-replicate` and the five `ppc-lab-replication-*-v1` schemas. The command uses only Python's standard library and the installed evidence/knowledge helpers; it requires no database server or network service. See `REPLICATION.md`.

