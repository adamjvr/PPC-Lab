# Reproducible Release Engineering

PPC Lab v3.1 adds `ppc-lab-release` so public source releases can be reproduced and independently verified without GitHub-specific tooling.

## Compatibility versions

Installed `ppclab/Version.hpp` exports:

```cpp
PPCLAB_VERSION_STRING
PPCLAB_CPP_API_VERSION
PPCLAB_CPP_ABI_VERSION
PPCLAB_TARGET_PROFILE_API_VERSION
```

For v3.1 the C++ API, C++ ABI contract marker, and target-profile API are all `1`. The CMake package continues to use same-major semantic-version compatibility. These numbers are deliberate compatibility promises; they are not incremented for ordinary implementation changes.

## Create a release manifest

```bash
ppc-lab-release manifest . --out RELEASE-MANIFEST.json
```

`ppc-lab-release-manifest-v1` records the PPC Lab version, GPL-3.0-only license id, public compatibility numbers, and a sorted path/size/mode/SHA-256 inventory of source files. Build trees, VCS state, Python caches, editor state, and archive outputs are excluded.

Verify it later with:

```bash
ppc-lab-release verify . RELEASE-MANIFEST.json
```

Any added, removed, resized, or byte-modified source file fails verification.

## Reproducible source ZIP

```bash
export SOURCE_DATE_EPOCH=946684800
ppc-lab-release archive . --out PPC-Lab-v3.1.0-source.zip
```

Files are sorted, ZIP timestamps are derived from `SOURCE_DATE_EPOCH`, regular/executable modes are normalized, and the archive embeds its source inventory as `RELEASE-MANIFEST.json`. Two archives made from identical source bytes with the same epoch are byte-identical.

The embedded release manifest intentionally does not include itself. After extraction:

```bash
ppc-lab-release verify ./PPC-Lab-v3.1.0-source \
  ./PPC-Lab-v3.1.0-source/RELEASE-MANIFEST.json
```

## Portable release qualification (v3.9.2+)

The authoritative post-v3 release gate is now available through the same installed release tool on Linux, macOS, Windows, self-hosted runners, and ordinary developer machines:

```bash
ppc-lab-release manifest . --out RELEASE-MANIFEST.json
ppc-lab-release qualify . \
  --build-dir build/qualification \
  --json build/qualification.json
```

`qualify` first verifies the checked-in `RELEASE-MANIFEST.json`, then configures with `CMAKE_BUILD_TYPE=Release` and Unicorn disabled by default, confirms that the release-critical tests are registered, builds with `--config Release`, and runs the complete CTest suite with failure output enabled. The default deliberately exercises the dependency-free builtin PPC backend so release qualification does not depend on optional Unicorn development packages. Use `--unicorn on` only as an additional environment-specific gate.

The resulting `ppc-lab-release-qualification-v1` report records PPC Lab/tool/platform versions, the manifest SHA-256, required-test discovery, command exit status, redacted command lines, and SHA-256 hashes of command output. Failure tails are bounded. Source/build roots are replaced by `$ROOT`/`$BUILD`; usernames, hostnames, environment variables, credentials, and PPC target bytes are not collected.

Hosted CI is therefore a transport for this gate, not the definition of the gate. A hosted-runner outage or account-side Actions restriction can be distinguished from a PPC Lab release failure by running the exact same qualification command locally or on another provider.

## Exact source archive certification (v3.9.3+)

Working-tree qualification is necessary but does not prove that the ZIP published to users contains the same source or remains buildable after clean extraction. The final distribution gate is therefore:

```bash
ppc-lab-release manifest . --out RELEASE-MANIFEST.json
ppc-lab-release certify . \
  --out build/PPC-Lab-v3.9.3-source.zip \
  --workspace build/certification \
  --json build/certification.json
```

`certify` creates the deterministic ZIP with the requested `SOURCE_DATE_EPOCH`, rejects unsafe/ambiguous members before extraction, clean-extracts the exact archive, verifies the embedded manifest against both the extracted bytes and the checked-in source manifest, then invokes `qualify` on that extracted source tree. The `ppc-lab-release-certification-v1` report records the exact archive SHA-256, size, member count, embedded/source manifest SHA-256 values, certification checks, and the nested privacy-minimal qualification report.

The certification workspace and JSON report should live under an excluded build directory (or outside the source tree) so producing evidence does not invalidate the checked-in source manifest. The archive itself is excluded from source manifests by release policy.

## Release gate

A public release should not be tagged until the working-tree qualification report is `ok: true` and the exact distribution archive has an `ok: true` certification report. For low-level debugging the older component commands remain useful, but they are no longer separate release policy:

```bash
python3 scripts/check_repository_invariants.py
./Tools/verify.command
ctest --test-dir build/release --output-on-failure
```

For post-v3 maintenance releases, target SDK, install-contract, compatibility, replication, release-engineering, release-qualification, and release-certification regressions remain release-critical.

## What this is not

This is not a binary-signing system, package-manager substitute, or legal provenance oracle. SHA-256 manifests prove byte identity relative to the manifest; they do not prove who authored a file or whether a target binary may be redistributed.

## Compatibility declaration (v3.2+)

Release manifests now embed `compatibility`, generated by the same code as `ppc-lab-compat snapshot`. Run the checked-in baseline gate before publishing:

```bash
ppc-lab-compat check compat/baselines/v3.1.0.json --root .
```

This complements byte reproducibility: the manifest states both *what bytes shipped* and *what public contracts the release promises*.
