# Long-term maintenance boundary

PPC Lab 3.0 is the end of the standing feature roadmap. From this release onward, development is **target-driven**.

## Merge a new capability when

- a real PPC binary exposes a missing loader/relocation/ISA/runtime behavior;
- an existing protocol has a reproducible correctness or security defect;
- a deployment requirement cannot be met by the current worker/fleet/API/control boundaries;
- accumulated evidence demonstrates a concrete research workflow that needs a small reusable primitive.

Every such change should arrive with a real or synthetic minimal reproduction and a permanent regression.

## Do not add a capability because

- another emulator has it;
- PPC64/little-endian/JIT/debugger support would look impressive on a feature list;
- a new database/service/framework is fashionable;
- a speculative abstraction might someday be useful.

## Compatibility policy

Stable `*-v1` schemas retain their established meanings. New optional fields may be additive. Incompatible semantics require a new schema identifier and, for persisted state, an explicit migration path with backup/rollback documentation.

The C++ package uses semantic major-version discovery. PPC Lab 3.x consumers should request:

```cmake
find_package(PPCLab 3.0 CONFIG REQUIRED)
```

## Private targets

PPC Lab source, tools, schemas, synthetic fixtures and documentation are GPL-3.0-only. Proprietary binaries supplied for research remain external inputs. Evidence/knowledge/corpus/triage/campaign/platform workflows continue to prefer hashes/provenance rather than copying private target bytes.

## v3.1 LTS compatibility surface

Post-v3 maintenance should preserve these explicit contract numbers unless a real incompatibility requires a deliberate major/minor transition:

- C++ API: `PPCLAB_CPP_API_VERSION=1`
- C++ ABI marker: `PPCLAB_CPP_ABI_VERSION=1`
- target-profile API: `PPCLAB_TARGET_PROFILE_API_VERSION=1`
- release manifest: `ppc-lab-release-manifest-v1`

New target projects should use `ppc-lab-target` rather than adding project-specific logic to generic source. Public releases should be produced or independently checked with `ppc-lab-release`.
