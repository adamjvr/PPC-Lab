# LTS replication and multi-site resilience

PPC Lab 3.9 adds an offline-safe replication layer for long-lived research installations. The design is deliberately content-addressed and transport-neutral: one site exports a verified ZIP, another site imports it, and the same bundle can travel by `scp`, removable media, object storage, backup tooling, or an operator-controlled synchronization job.

Replication does **not** copy PPC target binaries. It also does not copy live scheduler/control-plane queue state, process IDs, API credentials, environment files, logs, caches, or arbitrary files.

## Command surface

```bash
ppc-lab-replicate init /var/lib/ppc-lab/replication --site cortana

ppc-lab-replicate export /var/lib/ppc-lab/replication \
  --evidence /var/lib/ppc-lab/evidence \
  --knowledge /var/lib/ppc-lab/knowledge \
  --control /var/lib/ppc-lab/control \
  --out cortana-generation-1.zip

ppc-lab-replicate verify cortana-generation-1.zip

ppc-lab-replicate init /var/lib/ppc-lab/replication --site eve
ppc-lab-replicate import /var/lib/ppc-lab/replication cortana-generation-1.zip \
  --evidence /var/lib/ppc-lab/evidence \
  --knowledge /var/lib/ppc-lab/knowledge

ppc-lab-replicate status /var/lib/ppc-lab/replication --json
```

## What is replicated

### Evidence

The exporter reads the evidence SQLite index only to enumerate content hashes. Each canonical JSON evidence object is loaded from the evidence object store, canonicalized again, and required to match its SHA-256 filename. Imports use the ordinary `ppc-lab-evidence` ingestion path, so existing content is deduplicated rather than overwritten.

### Knowledge

Knowledge documents are exported from the `documents` table as canonical JSON and revalidated against their SHA-256 identity. Imports use the normal knowledge ingestion path, rebuilding graph relationships locally instead of shipping a mutable SQLite database image.

### Control history

Only terminal control-plane history is exported. Host-specific path fields such as scheduler manifests, run directories, log paths, and scheduler executable paths are removed. Live queue items, PID/lock state, scheduler process state, and `control.json` are intentionally not merged into another active control plane.

## Site generations and conflict detection

Every initialized replication store owns a portable site identifier and a monotonically increasing generation number. A successful export consumes exactly one local generation.

An importer writes an immutable receipt keyed by:

```text
source-site + generation
```

Importing the exact same bundle again is idempotent and reports `already-imported`. If a different, otherwise-valid bundle claims the same site/generation, import fails with a replication conflict. This prevents two divergent histories from silently occupying the same logical generation.

Generation gaps are allowed. PPC Lab does not assume a continuous network connection or a central coordinator.

## Bundle integrity

`ppc-lab-replication-bundle-v1` contains:

- source site and generation;
- a SHA-256 bundle identity derived from canonical manifest content;
- a SHA-256 and exact size for every member;
- explicit declarations that target binaries and live control state are absent;
- content-addressed evidence and knowledge JSON objects;
- optional redacted control history.

Verification rejects duplicate ZIP members, path traversal, symlink members, undeclared files, oversized members, hash/size mismatches, invalid semantic content hashes, malformed JSON, and bundles that do not explicitly preserve the no-target-binary policy.

## Multi-site operating model

PPC Lab does not elect a primary server and does not implement distributed consensus. Research evidence and knowledge are naturally mergeable because their durable identities are content hashes. Active campaign/control state is intentionally local to one control plane.

A practical deployment can therefore use:

```text
site A research server ──export──► replication ZIP ──import──► site B research server
site B research server ──export──► replication ZIP ──import──► site A research server
```

Both sites retain independent active workers/control queues while converging accumulated evidence and knowledge.

## Recovery relationship

`ppc-lab-backup` remains the tool for restoring one installation after loss. `ppc-lab-replicate` is for merging durable research knowledge between installations. A replication bundle is not a full disaster-recovery backup and intentionally omits live control state and deployment configuration.

## Stable contracts

v3.9 adds:

- `PPCLAB_REPLICATION_API_VERSION=1`
- `ppc-lab-replication-store-v1`
- `ppc-lab-replication-bundle-v1`
- `ppc-lab-replication-receipt-v1`
- `ppc-lab-replication-status-v1`
- `ppc-lab-replication-verify-v1`

These are additive members of the v3 LTS compatibility surface.
