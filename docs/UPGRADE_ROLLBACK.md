# Transactional upgrades, rollback, and release channels

PPC Lab 3.6 adds `ppc-lab-upgrade` for deterministic source-release intake. It is intended for the same repository-oriented delivery flow used by PPC Lab itself, while keeping `.git`, build directories, and private target inputs outside the replacement set.

## Preflight

```bash
ppc-lab-upgrade preflight PPC-Lab_v3.6.0.zip --current-root ~/GitHub/PPC-Lab --channel stable
```

Preflight verifies every archive member against `RELEASE-MANIFEST.json`, requires the incoming same-major LTS compatibility declaration to preserve the currently installed public API/ABI/schema/tool surface, and enforces the selected channel policy.

## Channels

The installed `share/ppc-lab/channels/release-channels.json` defines `stable`, `candidate`, and optional `pinned` policy. Stable rejects prereleases, major changes, and downgrades. Channel configuration is ordinary auditable JSON using `ppc-lab-release-channel-v1`.

## Apply and rollback

```bash
ppc-lab-upgrade apply release.zip --repo-root ~/GitHub/PPC-Lab --backup-dir ~/.local/state/ppc-lab/upgrades
ppc-lab-upgrade rollback ~/.local/state/ppc-lab/upgrades/<transaction>.json --repo-root ~/GitHub/PPC-Lab
```

Before changing managed source files, apply creates a SHA-256-pinned rollback ZIP. `.git`, build directories and other excluded runtime state are preserved. If apply fails after modification begins, rollback is attempted automatically. Explicit rollback verifies the snapshot hash before restoring it.

This is not a package manager and does not run `git commit`, push, or privileged deployment actions. Run normal project verification after apply; commit/push remains an explicit operator action.

## Security boundary

Archive traversal, symlinks, extra/unmanifested members, hash mismatches, compatibility regressions, disallowed downgrades and channel violations are rejected before source replacement. Private PPC target binaries are not copied into transaction metadata or rollback policy beyond whatever the operator has incorrectly placed inside the source repository itself; keep private target roots outside the repository as documented elsewhere.
