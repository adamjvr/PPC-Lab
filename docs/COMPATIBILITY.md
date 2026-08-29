# LTS compatibility assurance

PPC Lab v3.2 adds a dependency-free compatibility gate for the completed v3 platform. It is release assurance, not a new emulation subsystem.

## Public compatibility declaration

```bash
ppc-lab-compat snapshot .
ppc-lab-compat check compat/baselines/v3.1.0.json --root .
```

The snapshot records the platform major, C++ API/ABI markers, target-profile/release/compatibility APIs, installed public tools, stable JSON-schema filenames, and persisted evidence/knowledge/control format levels. A same-major release may add contracts, but it fails the LTS check if it removes a baseline schema/tool, changes a public API/ABI marker, changes major version, or declares a persisted format older than the baseline.

## Persisted-state audit

```bash
ppc-lab-compat state --evidence ./evidence --knowledge ./knowledge --control ./control --json
```

This reuses the v3 platform upgrade checker and never mutates data. Migration remains an explicit `ppc-lab-platform migrate --yes` operation.

## Release integration

`ppc-lab-release manifest` and deterministic source archives embed the full compatibility snapshot inside `RELEASE-MANIFEST.json`. A published source archive therefore declares both its byte inventory and its compatibility surface.

`compat/baselines/v3.1.0.json` is the first v3 LTS baseline. It is intentionally checked into source control. Do not edit old baselines to make a breaking release pass; add a deliberate new-major baseline instead.
