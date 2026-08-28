# Research knowledge graph

PPC Lab v2.4 adds `ppc-lab-knowledge`, a dependency-free SQLite relationship index over accumulated PPC Lab research artifacts. It is designed to answer questions that become difficult once a project has hundreds or thousands of traces, corpus cases, triage bundles, campaign summaries, and evidence records:

- Which targets have produced this same stable behavior?
- Where else has this function name or address appeared?
- Which corpus cases protect a target?
- Which campaign or triage artifact led to this finding?
- Which observed calls and hot addresses are known for a target?
- Can accumulated findings be exported back into Ghidra, IDA, or Binary Ninja?

The graph stores JSON research evidence and hashes. **It does not copy target binary bytes.** Target identity is SHA-256-first, so private binaries can remain in project-controlled storage while their relationships stay queryable.

## Storage model

A graph directory contains one `knowledge.sqlite3` database. The database stores:

- canonical PPC Lab JSON documents and source provenance;
- typed nodes such as `target`, `document`, `schema`, `symbol`, `function`, `address`, `behavior`, `coverage`, `corpus-case`, `triage`, and `campaign`;
- typed relationships such as `targets`, `defines-symbol`, `executed`, `observed-call`, `has-behavior`, `has-coverage`, `regresses-target`, and `researched-target`;
- target-scoped address/function identity where a target SHA-256 is known.

No graph server is required. SQLite WAL mode and normal filesystem backup/snapshot practices are sufficient.

## Initialize

```bash
ppc-lab-knowledge init /srv/ppc-knowledge
```

## Ingest research artifacts

Ingest one file or recursively ingest JSON from directories:

```bash
ppc-lab-knowledge ingest /srv/ppc-knowledge \
  /srv/results/campaign-001 \
  /srv/triage/case-17 \
  /srv/corpus/cases
```

Only JSON objects whose schema begins with `ppc-lab-` are indexed. Canonically identical JSON documents deduplicate while every source path/raw SHA-256 is retained as provenance.

Some loader metadata or trace-analysis documents intentionally do not carry target bytes or target hashes. When the researcher already knows the target hash, scope those artifacts explicitly:

```bash
ppc-lab-knowledge ingest /srv/ppc-knowledge \
  /tmp/target.metadata.json /tmp/target.analysis.json \
  --target-sha256 8f31d9...<64 hex chars>
```

This does not read or copy the binary; it only assigns target identity to those evidence documents.

## Synchronize an evidence store

The v1.4 evidence store is still the durable content-addressed evidence archive. v2.4 can index its objects directly:

```bash
ppc-lab-knowledge sync-evidence /srv/ppc-knowledge /srv/ppc-evidence
```

The graph and evidence store solve different problems:

- **evidence store:** preserve/deduplicate/query artifacts;
- **knowledge graph:** connect artifacts and expose relationships across runs/projects.

## Query nodes

```bash
ppc-lab-knowledge query /srv/ppc-knowledge --type target --json
ppc-lab-knowledge query /srv/ppc-knowledge --type function --label Render --json
ppc-lab-knowledge query /srv/ppc-knowledge --target-sha256 8f31d9 --address 0x10004268 --json
```

Target SHA values may be unambiguous prefixes for queries and export.

## Ask “where have we seen this behavior before?”

Behavior nodes are deterministic fingerprints extracted from stable result/corpus behavior or the explorer's explicit `behavior_sha256`. Find a behavior node and walk two hops:

```bash
ppc-lab-knowledge query /srv/ppc-knowledge --type behavior --json
ppc-lab-knowledge related /srv/ppc-knowledge behavior:<sha256> --depth 2 --json
```

A shared behavior node can connect documents from different target hashes. That is the intended cross-project reuse mechanism: PPC Lab records the relationship without claiming two routines are semantically identical merely because one observation matched.

## Relationship paths

Use `path` to explain how two findings are connected:

```bash
ppc-lab-knowledge path /srv/ppc-knowledge \
  target:<sha256> function:<sha256>:InterestingRoutine --json
```

Traversal is undirected for discovery/explanation, while every returned edge retains its original direction and relation name.

## Reports and integrity

```bash
ppc-lab-knowledge report /srv/ppc-knowledge --json
ppc-lab-knowledge verify /srv/ppc-knowledge --json
```

`verify` runs SQLite integrity checks, recomputes the canonical SHA-256 of every stored research document, and checks for dangling graph references.

## Decompiler export

Accumulated target-scoped knowledge can be exported back into the existing neutral `ppc-lab-evidence-v1` format:

```bash
ppc-lab-knowledge export-decompiler /srv/ppc-knowledge \
  --target-sha256 8f31d9 \
  --json /tmp/target.knowledge.evidence.json
```

The export aggregates available symbols plus execution/hot-PC observations, observed calls, differential-triage divergence points, and existing manual/evidence annotations. Use the existing thin Ghidra/IDA/Binary Ninja import scripts unchanged.

## Identity and interpretation rules

1. **Targets are SHA-256 identities.** Paths and filenames are provenance, not identity.
2. **Addresses are target-scoped when possible.** `0x10000000` in two binaries is not automatically the same program entity.
3. **Function names are observations, not proof of equivalence.** Cross-target label matches are useful search hints only.
4. **Behavior matches are evidence relationships, not semantic proofs.** Confirm with traces/state/static analysis before drawing stronger conclusions.
5. **Private binaries remain external.** The graph contains hashes and JSON evidence, not target bytes.
6. **Ingestion is additive and deterministic.** Existing schema meanings are not mutated by graph indexing.

## Stable v2.4 contracts

The additive v2.4 schemas are:

- `ppc-lab-knowledge-query-v1`
- `ppc-lab-knowledge-report-v1`
- `ppc-lab-knowledge-related-v1`
- `ppc-lab-knowledge-path-v1`
- `ppc-lab-knowledge-verify-v1`

Decompiler export intentionally reuses `ppc-lab-evidence-v1` rather than introducing a decompiler-specific graph format.
