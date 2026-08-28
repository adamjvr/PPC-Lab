# Automated hypothesis engine

PPC Lab v2.5 adds a deterministic hypothesis layer above recorded execution evidence. It is designed to answer questions such as:

- does an unexplained GPR look like a boolean, selector, pointer, count, or generic scalar?
- does a probed `writes_u32`/`writes_f32` location behave like routine state?
- which observed cases actually support that interpretation?
- what bounded follow-up experiment would most directly challenge the candidate?
- has the claim earned promotion into the knowledge graph, or is it still only a candidate?

The engine is **not an opaque AI dependency**. It uses recorded PPC Lab cases, transparent heuristics, explicit scores, and ordinary PPC Lab execution evidence.

## Commands

Analyze an existing guided/cartesian/adaptive exploration:

```bash
ppc-lab-hypothesize analyze ./exploration \
  --manifest ./explore.json \
  --json ./hypotheses.json
```

Generate bounded follow-up experiments:

```bash
ppc-lab-hypothesize experiments ./hypotheses.json \
  --out ./hypothesis-experiments \
  --top 8
```

Each candidate with a recoverable exploration manifest produces both:

- `hyp-NNN.experiment.json` — `ppc-lab-hypothesis-experiment-v1`, carrying the claim and embedded experiment;
- `hyp-NNN.exploration.json` — a directly runnable `ppc-lab-exploration-v1` manifest.

Run that exploration normally with `ppc-lab-explore`. The hypothesis engine never bypasses the worker/root/timeout/execution contracts.

Promote only after verifying the exact case evidence used by the report:

```bash
ppc-lab-hypothesize promote ./hypotheses.json hyp-001 \
  --evidence ./exploration \
  --json ./hyp-001.supported.json
```

Promotion checks the recorded SHA-256 of each supporting case and refuses to promote if the evidence changed after analysis. Defaults require confidence >= 0.55 and at least two successful supporting executions. Thresholds are explicit CLI policy, not hidden state.

## Role inference

Current deterministic role families are intentionally small:

| Role | Typical evidence |
|---|---|
| `boolean-flag` | integer input domain dominated by 0/1 with observable behavioral effect |
| `selector-enum` | small integer domain partitions behavior or coverage |
| `count-or-length` | numeric input strongly correlates with executed instruction count |
| `pointer-or-address` | aligned high-valued GPR inputs consistent with address-like use |
| `scalar-argument` | GPR affects behavior without stronger role evidence |
| `floating-argument` | explored floating call register |
| `state-field` | explored `writes_u32` location |
| `floating-state-field` | explored `writes_f32` location |
| `import-binding` | varied imported-symbol binding |
| `environment-result` | varied syscall return contract |

These are **hypotheses, not type recovery guarantees**. A high confidence means the recorded evidence strongly matches the heuristic, not that PPC Lab has proven source-level intent.

## Confidence and evidence

Every candidate includes:

- the mutation subject/path;
- proposed role and plain-language claim;
- confidence in `[0,1]`;
- distinct-value, behavior-partition, coverage-partition, failure, and instruction-correlation metrics;
- supporting and contradicting case indices;
- supporting behavior SHA-256 identities;
- suggested values for a targeted follow-up;
- an explicit exploration manifest when the source manifest is available.

No hidden model weights or remote service calls exist. The report records enough information to understand why the candidate ranked where it did.

## Evidence-gated promotion

`ppc-lab-hypothesis-report-v1` is a candidate report. It is safe to ingest into the knowledge graph, but graph edges from it are `proposes-hypothesis`.

`ppc-lab-hypothesis-v1` is produced by explicit promotion after verified PPC Lab evidence. A supported record gains `supports-hypothesis` graph relationships. Promotion does not mutate the original report or exploration.

If evidence is later contradicted, create new evidence and a new hypothesis record rather than silently rewriting old research history.

## Knowledge graph integration

```bash
ppc-lab-knowledge ingest /srv/ppc-knowledge \
  ./hypotheses.json ./hyp-001.supported.json --json

ppc-lab-knowledge query /srv/ppc-knowledge --type hypothesis --json
```

Hypotheses are linked to target SHA-256 nodes and, when available, supporting behavior fingerprints. `writes_u32.ADDRESS` and `writes_f32.ADDRESS` candidates also connect to target-scoped address nodes. Supported state-field hypotheses can therefore appear in `export-decompiler` output as `supported-hypothesis` annotations.

## Reproducibility and safety

- target binaries are never copied into hypothesis reports or promoted records;
- target identity remains SHA-256 plus size through normal exploration provenance;
- case evidence is content-pinned at analysis time and rechecked at promotion;
- generated experiments use the normal exploration schema and therefore inherit mutation-root restrictions and worker filesystem containment;
- candidate generation is deterministic for identical exploration evidence and manifest content;
- the engine does not auto-promote claims.

## What v2.5 intentionally does not claim

PPC Lab does not infer C/C++ source types, object layouts, semantic variable names, or complete calling conventions from thin evidence. It generates reviewable experimental hypotheses that can be tested by the existing execution/coverage/corpus/triage machinery.
