# Release acceptance

PPC Lab major releases have two different gates:

## Core regression gate

The ordinary CTest suite covers loaders, PPC execution, runtime boundaries, worker/fleet/server layers, evidence/corpus/triage/exploration/campaign/control/knowledge/hypothesis behavior, repository invariants, and the installed CMake package.

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j
ctest --test-dir build/release --output-on-failure
```

## Mature-platform acceptance gate

`ppc-lab-platform acceptance` verifies that the major subsystem boundaries compose correctly in a clean operational workflow. This test is intentionally serial because it launches real worker/tool subprocesses.

```bash
ppc-lab-platform acceptance --workspace /tmp/ppc-lab-acceptance --json
```

A v3 release should not be published if this path fails even when isolated unit tests pass.

## Archive certification

The downloadable source archive is the artifact that must be certified:

1. create a source-only archive (exclude build trees, Python caches, transient databases and private targets);
2. extract into an empty directory;
3. configure/build the extracted copy;
4. run repository invariants, installed-package contract, platform consolidation, and mature-platform acceptance;
5. record SHA-256 of the exact archive.
