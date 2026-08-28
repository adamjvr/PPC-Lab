# Mature platform operations

PPC Lab 3.0 consolidates the v1/v2 subsystem stack without creating another execution engine. The operator entry point is `ppc-lab-platform`.

## Whole-platform status

```bash
ppc-lab-platform status --json
ppc-lab-platform doctor --json
```

`status` checks that the core executable and the installed companion commands are discoverable and reports the core version/backends. `doctor` additionally runs the core microtest doctor and can audit persisted state:

```bash
ppc-lab-platform doctor \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control \
  --json
```

The operator command is intentionally a coordinator. It does not duplicate worker, fleet, campaign, evidence, knowledge, or execution semantics.

## Mature-platform acceptance

A release or newly provisioned server can run a synthetic end-to-end acceptance:

```bash
ppc-lab-platform acceptance \
  --workspace /tmp/ppc-lab-acceptance \
  --json
```

The acceptance fixture is generated locally and is redistributable. It verifies:

1. ELF32 PPC big-endian intake;
2. real PPC execution under the builtin backend;
3. deterministic guided/cartesian exploration;
4. evidence-store ingestion and integrity verification;
5. hypothesis analysis and evidence-gated promotion;
6. knowledge-graph ingestion and query.

The acceptance report uses `ppc-lab-acceptance-report-v1`. It does not copy or require proprietary target binaries.

## Operator contracts

PPC Lab 3.0 adds three additive machine-readable contracts:

- `ppc-lab-platform-status-v1`
- `ppc-lab-upgrade-report-v1`
- `ppc-lab-acceptance-report-v1`

They describe orchestration/operations around the already-stable subsystem protocols. They do not replace those protocols.
