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

## v3.2 compatibility gate

Before a target-driven v3.x patch is released, run `ppc-lab-compat check compat/baselines/v3.1.0.json --root .`. A failure is a release blocker unless the project intentionally moves to a new major compatibility line. Old baselines are immutable release evidence.


## v3.3 support bundle gate

For target-driven defects that cannot be reproduced immediately, collect `ppc-lab-support diagnose` first. If a shareable artifact is needed, use `ppc-lab-support bundle` and run `ppc-lab-support verify` before attaching it to an issue. Do not replace this with a generic tar/zip of server state: support bundles are deliberately constrained so private target binaries and persisted research databases are not swept into bug reports.

## LTS disaster-recovery maintenance

Persistent-state format changes must preserve the v3.5 backup boundary. Before changing evidence, knowledge, or control persistence, maintainers must keep `ppc-lab-backup create/verify/restore` and `ppc-lab-compat state` interoperable or explicitly treat the change as a major-version compatibility event.

Do not broaden the backup format into a generic server archive. Private target inputs, API-token environment files, caches, arbitrary binary attachments, and general logs remain outside `ppc-lab-backup-v1`.

## v3.6 transactional upgrade gate

Public v3.x releases should pass `ppc-lab-upgrade preflight` on the stable channel before source replacement. The updater is intentionally repository/source oriented: it verifies the deterministic release manifest and v3 compatibility declaration, preserves Git/build state, and produces a rollback transaction before changing managed files. Do not weaken manifest, path, symlink, downgrade, or rollback-hash checks for convenience.

## v3.7 observability gate

Operational regressions should be measured rather than inferred from anecdotal queue delay. Long-running servers should periodically collect `ppc-lab-observe sample` data and use `report/check/capacity` when changing worker-slot counts, scheduler policy, storage layout, or host hardware.

The observability store is deliberately JSON-only and target-neutral. Do not add target binaries, environment-secret capture, arbitrary process dumps, or a mandatory external metrics/database stack to `ppc-lab-observability-*-v1`. A future exporter to another monitoring system should consume these stable reports rather than redefine the sample contract.

### Security credentials and audit logs

Treat auth stores and audit logs as operational state, not source artifacts. Rotate credentials when operators/automation change, revoke unused tokens, and periodically run `ppc-lab-security audit-verify`. Do not add bearer tokens to diagnostics, support bundles, Git, or behavioral corpora.
## v3.9 replication gate

Multi-site synchronization must preserve the `ppc-lab-replication-*-v1` contracts. Replication is content-addressed research metadata, not generic file synchronization: private target bytes, credentials, arbitrary logs/files, and active scheduler/control state must remain excluded. A reused site/generation with a different bundle identity is a hard conflict and must never be silently accepted.

Use `ppc-lab-backup` for single-site disaster recovery and `ppc-lab-replicate` for cross-site convergence. Do not weaken either boundary by treating replication ZIPs as full server backups.
## v3.9.2 portable qualification gate

Release validity must not depend on one hosted CI vendor. Regenerate `RELEASE-MANIFEST.json`, then run `ppc-lab-release qualify . --build-dir build/qualification --json build/qualification.json`. The report must be `ok: true`; all release-critical tests must be discovered before compilation; and the complete CTest run must pass. Treat a workflow that fails before checkout/qualification starts as runner or account infrastructure failure, not as evidence of a PPC Lab source regression.

The qualification report is deliberately target-neutral and privacy-minimal: no target binaries, usernames, hostnames, environment dumps, or credentials. Preserve this boundary when extending the release gate.

## v3.9.3 exact archive certification gate

The final public-release artifact should be certified, not merely created. After regenerating `RELEASE-MANIFEST.json`, run `ppc-lab-release certify . --out build/PPC-Lab-source.zip --workspace build/certification --json build/certification.json`. Certification must validate the ZIP member envelope, prove the embedded manifest is byte-identical to the checked-in source manifest, and produce an `ok: true` nested release-qualification report from the clean extraction.

Do not weaken the archive envelope to accept path traversal, duplicate names, backslash aliases, directory entries, symlinks, device files, or other non-regular members. Certification reports remain metadata-only and must not capture private PPC target bytes, credentials, usernames, hostnames, or environment dumps.

## v3.9.1 CI/install-contract gate

For patch releases, keep the installed CMake package usable from both single-configuration and multi-configuration generators. Do not force `--config` during installation of a single-configuration build with no matching configuration export. CI should also keep `fail-fast: false` so one hosted runner cannot erase evidence from the other supported operating systems.

