# PPC Lab evidence store

`ppc-lab-evidence` turns accumulated PPC Lab JSON output into a durable, queryable research archive without introducing a daemon, external database, cloud service, or mandatory third-party Python package.

The store has two parts:

- `objects/sha256/..` contains canonical UTF-8 JSON objects addressed by SHA-256;
- `evidence.sqlite3` is a local SQLite index for fast lookup and provenance.

SQLite is an implementation detail of the local store, not a network service. The object SHA is the durable identity; the database can be inspected/verified independently.

## Critical boundary: target binaries are not archived

Evidence ingestion copies **PPC Lab JSON evidence only**. It does not follow `image.path`, does not copy ELF/Mach-O/PEF/raw targets, and does not turn the store into an executable/firmware archive.

When orchestration/fleet records contain input fingerprints, the index records their logical path, size, and SHA-256. This is enough to correlate all experiments run against the same target bytes while leaving redistribution/storage policy to the owning research project.

## Initialize

```bash
ppc-lab-evidence init /srv/ppc-evidence
```

Initialization is idempotent. Current on-disk schema version: `1`.

## Ingest

A file:

```bash
ppc-lab-evidence ingest /srv/ppc-evidence result.json
```

One or more result directories:

```bash
ppc-lab-evidence ingest /srv/ppc-evidence \
  /srv/results/run-001 \
  /srv/results/run-002
```

Directories are searched recursively for `*.json`. By default malformed JSON and JSON without a `ppc-lab-*` schema are skipped and counted. `--strict` converts either condition into an ingestion error.

### Semantic deduplication

The object identity is SHA-256 over canonical JSON (sorted keys, compact separators, UTF-8), not over the original file formatting. Therefore pretty-printed and minified copies of the same evidence become one artifact.

Every observed source is still preserved in the `sources` table with:

- original path;
- original/raw file SHA-256;
- raw byte size;
- ingestion timestamp.

This gives deduplication without losing provenance.

## Automatic publication

Local orchestration:

```bash
ppc-lab-orchestrate manifest.json \
  --out /srv/results/run-003 \
  --root /srv/research \
  --evidence-store /srv/ppc-evidence
```

Distributed fleet:

```bash
ppc-lab-fleet fleet.json \
  --local-root /srv/research \
  --out /srv/results/run-004 \
  --evidence-store /srv/ppc-evidence
```

Publication happens after `summary.json` is written. If `--evidence-store` was explicitly requested and ingestion fails, the orchestration/fleet command returns an infrastructure error rather than claiming complete publication.

## Query

Human-readable latest-first query:

```bash
ppc-lab-evidence query /srv/ppc-evidence --backend builtin-ppc32be --ok yes
```

Machine-readable query:

```bash
ppc-lab-evidence query /srv/ppc-evidence \
  --engine-version 1.4.0 \
  --host ppc-worker-02 \
  --input-sha256 8f31d9 \
  --json
```

Supported indexed filters:

- `--schema` exact PPC Lab document schema;
- `--engine-version` exact engine version;
- `--backend` exact execution backend;
- `--stop-reason` exact execution stop reason;
- `--host` exact fleet host;
- `--name` substring match over orchestration/fleet job name;
- `--ok yes|no` worker/result success state when available;
- `--cache-key PREFIX` deterministic job cache-key prefix;
- `--input-sha256 PREFIX` target-input content-hash prefix;
- `--limit N`;
- `--oldest` to reverse the default newest-first artifact order.

The JSON query contract is `ppc-lab-evidence-query-v1`.

## Show an artifact

Use integer artifact id or an unambiguous SHA-256 prefix (minimum 8 hex characters):

```bash
ppc-lab-evidence show /srv/ppc-evidence 42
ppc-lab-evidence show /srv/ppc-evidence 91ab53d40c72
```

The default prints the original semantic JSON document. Add `--metadata` to inspect indexed fields, every source provenance record, and target-input hashes instead.

## Report

```bash
ppc-lab-evidence report /srv/ppc-evidence
ppc-lab-evidence report /srv/ppc-evidence --json
```

Reports aggregate artifact/source counts, unique target-input hashes, canonical evidence bytes, success state, document schemas, engine versions, backends, fleet hosts, and stop reasons. JSON uses `ppc-lab-evidence-report-v1`.

## Integrity verification

```bash
ppc-lab-evidence verify /srv/ppc-evidence
```

Verification checks:

1. the store schema version;
2. every database artifact has an object file;
3. object byte length matches the database;
4. SHA-256 of the actual canonical object bytes matches its identity;
5. object files not referenced by the database are reported as orphans.

Missing/corrupt objects make the command exit nonzero. Orphans are reported but do not make the indexed evidence invalid because they can be left behind by an interrupted transaction/copy and are not referenced by the database.

The JSON verification contract is `ppc-lab-evidence-verify-v1`.

## Backup and movement

The store is self-contained. For a quiescent store, back up the entire directory, not just `evidence.sqlite3`:

```text
/srv/ppc-evidence/
├── evidence.sqlite3
└── objects/
    └── sha256/
```

For a store that may be receiving writes, use normal SQLite-safe backup/snapshot procedures or stop publishers briefly. Do not copy only a live database file while ignoring its WAL state.

## Concurrency

SQLite WAL mode is enabled and individual object writes are atomic. This supports ordinary parallel PPC Lab publishers on one server. v1.4 does not claim distributed multi-writer filesystem semantics across unreliable/NFS-like storage. For fleet deployment, publish centrally on the controller host or use project-owned storage synchronization around the store.

## Compatibility

The on-disk database schema and the machine-readable query/report/verify JSON schemas are versioned separately. v1.x changes should prefer additive fields. A breaking query/report contract uses a new `*-vN` identifier; a breaking database layout requires an explicit store-schema migration rather than silently reinterpreting an old database.
