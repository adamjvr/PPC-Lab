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
- `bin/ppc-lab-worker`, `bin/ppc-lab-orchestrate`, and `bin/ppc-lab-fleet`;
- the static PPC Lab core library;
- `include/ppclab/ppc/*.hpp`;
- `PPCLabConfig.cmake`, `PPCLabConfigVersion.cmake`, and exported targets;
- README, changelog, license, and detailed docs.

## Consume from CMake

```cmake
cmake_minimum_required(VERSION 3.20)
project(MyResearchTool LANGUAGES CXX)
find_package(PPCLab 1.0 CONFIG REQUIRED)
add_executable(my-tool main.cpp)
target_link_libraries(my-tool PRIVATE PPCLab::core)
```

The exported core target propagates the required C++20 language feature and installed include path. Do not hard-code the PPC Lab source-tree include directory.

## Release contract test

`tests/test_install_contract.py` installs the current build into a temporary prefix, executes the installed CLI, discovers the package through `find_package(PPCLab CONFIG)`, and compiles a separate downstream consumer. This test exists specifically to catch packaging/export mistakes that ordinary in-tree tests cannot see.

## Server-tool installation

The same install step places `ppc-lab-worker`, `ppc-lab-orchestrate`, and `ppc-lab-fleet` in the install `bin` directory and the v1 JSON schemas under `share/ppc-lab/schemas/`. These tools use only Python's standard library. Fleet SSH transport additionally expects ordinary OpenSSH `ssh`/`scp` commands on the controller.

The worker locates `ppc-lab` through `--ppc-lab`, `PPC_LAB_BIN`, or `PATH`. A normal fleet host therefore needs the installed `bin` directory on the noninteractive SSH `PATH`; see `docs/FLEET.md`.
