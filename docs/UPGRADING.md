# Upgrading PPC Lab persisted state

PPC Lab intentionally keeps target binaries outside its evidence and knowledge stores. Upgrades operate on PPC Lab metadata/databases only.

## Before upgrading

1. Stop `ppc-lab-control serve` and any campaign/scheduler process that writes the same state.
2. Preserve the existing repository/release version used to create current evidence.
3. Run an upgrade audit:

```bash
ppc-lab-platform upgrade-check \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control \
  --json
```

Exit code `0` means the persisted schemas are structurally compatible with the v3 migration framework. Incompatible or unknown schema versions are rejected rather than guessed.

## v3.0 migration

PPC Lab 3.0 introduces explicit persisted-format migration metadata. Apply it with:

```bash
ppc-lab-platform migrate \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control \
  --yes --json
```

The operation is idempotent. Before the first change it creates safety backups:

```text
evidence.sqlite3.pre-v3.0.0.bak
knowledge.sqlite3.pre-v3.0.0.bak
control.json.pre-v3.0.0.bak
```

For the existing v1 database/control layouts, v3.0 does not rewrite research artifacts or change evidence identities. It records `platform_format_version=1` and `last_migrated_by=3.0.0`, providing an explicit future migration anchor.

## Post-upgrade verification

```bash
ppc-lab-platform doctor \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control

ppc-lab-evidence verify /srv/ppc-evidence
ppc-lab-knowledge verify /srv/ppc-knowledge
```

Never bypass an incompatible-schema error by manually changing a version field. Add an explicit migration with a regression fixture instead.
