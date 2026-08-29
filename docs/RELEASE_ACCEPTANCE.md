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

The downloadable source archive is the artifact that must be certified. PPC Lab 3.9.3 automates the clean-room sequence:

```bash
ppc-lab-release manifest . --out RELEASE-MANIFEST.json
ppc-lab-release certify . \
  --out build/PPC-Lab-source.zip \
  --workspace build/certification \
  --json build/certification.json
```

The command creates the deterministic source-only ZIP, rejects unsafe/ambiguous archive members, extracts into a clean workspace, verifies the embedded manifest, runs the complete portable qualification gate against the extracted copy, and records the SHA-256 of the exact archive. A public archive is not accepted unless the certification report says `ok: true`.
