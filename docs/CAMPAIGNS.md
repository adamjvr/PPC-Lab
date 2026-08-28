# Autonomous research campaigns

`ppc-lab-campaign` is the v2.0 composition layer for bounded, reproducible PPC research runs. It does not replace the execution engine, worker protocol, guided explorer, behavioral corpus, differential triage, or evidence store. It drives those already-stable components in a checkpointed sequence and produces one durable campaign summary.

The intended use is a server or research workstation where the question is no longer “run this one routine,” but:

> explore a bounded input domain, preserve novel behavior, check that the preserved cases still replay, triage selected discoveries across two engine/backend configurations, and publish the resulting evidence without manually babysitting every step.

## Minimal campaign

```json
{
  "schema": "ppc-lab-campaign-v1",
  "name": "constructor-sweep",
  "budgets": {
    "max_cases": 64,
    "max_triage_cases": 8,
    "case_timeout_seconds": 30,
    "wall_seconds": 3600
  },
  "exploration": {
    "schema": "ppc-lab-exploration-v1",
    "strategy": "guided",
    "max_cases": 64,
    "base_job": {
      "schema": "ppc-lab-job-v1",
      "id": "constructor",
      "image": {"path": "target.pef"},
      "execution": {"backend": "builtin", "entry": "0x10004000", "max_instructions": 250000},
      "registers": {"r3": 0, "r4": 0}
    },
    "axes": [
      {"path": "registers.r3", "values": [0, 1, 4096]},
      {"path": "registers.r4", "values": [0, 1, 64, 128]}
    ]
  },
  "corpus": {
    "path": "./corpus",
    "promote_novel": true,
    "verify": true,
    "replay": true
  },
  "triage": {
    "enabled": true,
    "select": "novel-or-failed",
    "left_backend": "builtin",
    "right_backend": "auto"
  },
  "evidence": {
    "publish": true,
    "store": "./evidence",
    "verify": true
  }
}
```

Run it:

```bash
ppc-lab-campaign campaign.json --out ./runs/campaign-001
```

Resume an interrupted campaign:

```bash
ppc-lab-campaign campaign.json --out ./runs/campaign-001 --resume
```

Validate the full plan and input-root boundary without executing target code:

```bash
ppc-lab-campaign campaign.json --out ./runs/dry-run --dry-run
```

## Stage model

A v2.1 campaign runs five durable stages.

### 1. Exploration

The inline `ppc-lab-exploration-v1` manifest is passed to `ppc-lab-explore`. Structural target paths are resolved under the campaign root before execution. `budgets.max_cases` can only tighten the exploration manifest's own limit.

Successful coverage- or behavior-novel cases can be promoted immediately into the behavioral corpus. Private target binaries are referenced by SHA-256 through the corpus contract; they are not copied merely because a campaign promoted a case.

### 2. Campaign intelligence

When enabled, `ppc-lab-prioritize` analyzes the completed exploration frontier before triage. It writes `intelligence.json`, ranks cases with explicit deterministic weights, summarizes axis/value yield, and reports whether the exploration tail appears saturated. This stage does not execute guest code and does not alter the hard case or triage budgets.

The ranking is later applied only to cases that already satisfy `triage.select`; `budgets.max_triage_cases` is then enforced on the priority-ordered eligible set.

### 3. Corpus verification and replay

If a corpus was created or already exists, the campaign can run:

- structural/hash verification;
- replay against the current engine;
- external private-input resolution from the campaign root.

A replay regression is considered stronger than an ordinary research finding: the final campaign status becomes `complete-with-regressions` and the campaign exits nonzero.

### 4. Differential triage

Selected exploration cases are rerun through `ppc-lab-triage`. Selection policies are:

- `novel`;
- `failed`;
- `novel-or-failed` (default);
- `all`.

`budgets.max_triage_cases` bounds the amount of automatic triage. Every selected case gets a standard v1.8 triage report and bundle. The campaign does not copy target binaries into those bundles.

The left and right engine executables may be different installations:

```bash
ppc-lab-campaign campaign.json \
  --out ./runs/cross-version \
  --right-ppc-lab /opt/ppc-lab-old/bin/ppc-lab \
  --right-worker /opt/ppc-lab-old/bin/ppc-lab-worker
```

This makes the campaign layer usable for current-vs-old-engine regression hunting as well as builtin-vs-Unicorn checks.

### 5. Evidence publication

After generated evidence is final, the campaign can ingest:

- exploration case/summary JSON;
- triage reports/bundles;
- corpus replay summaries;
- corpus case metadata.

The evidence store is verified after publication when `evidence.verify` is true. Like the underlying evidence subsystem, campaign publication stores PPC Lab evidence JSON, not target binary bytes.

## Output tree

A typical run contains:

```text
run/
├── campaign.exploration.json
├── state.json
├── summary.json
├── intelligence.json
├── exploration/
│   ├── summary.json
│   └── cases/
├── corpus-replay.json
└── triage/
    ├── summary.json
    └── 00000/
        ├── job.json
        ├── triage.json
        └── bundle/
```

The corpus and evidence store may live inside or outside the run directory depending on the campaign manifest. Keeping long-lived corpus/evidence roots outside ephemeral run directories is usually preferable on a server.

## Checkpoint and resume contract

`state.json` uses `ppc-lab-campaign-state-v1` and records:

- the SHA-256 of the campaign manifest;
- PPC Lab engine version;
- completed stages, including the v2.1 `intelligence` checkpoint;
- per-stage timing/result metadata.

`--resume` requires the exact same manifest hash and PPC Lab version. PPC Lab intentionally refuses to “resume” a modified campaign or a run after silently changing engine versions. Start a new output directory when either changes.

A completed stage is not rerun during resume. This makes campaigns suitable for long server runs without needing an external queue/database solely for checkpointing.

## Budgets

`budgets` supports:

| Field | Meaning |
|---|---|
| `max_cases` | Upper bound for guided/cartesian exploration executions. |
| `max_triage_cases` | Maximum selected exploration cases automatically triaged. `0` disables triage. |
| `case_timeout_seconds` | Per worker/corpus/triage execution wall-clock limit. |
| `wall_seconds` | Optional overall campaign wall-clock budget checked before each stage/case launch. |

These are containment mechanisms, not performance promises. Guest instruction limits still belong in each `ppc-lab-job-v1` execution block.

## Final status

`summary.json` uses `ppc-lab-campaign-summary-v1`.

Possible normal statuses include:

- `complete` — no campaign-level findings;
- `complete-with-findings` — guest failures or differential divergences were found and preserved for research;
- `complete-with-regressions` — corpus replay no longer matches a blessed behavioral baseline;
- `dry-run` — plan/root validation completed without executing target code.

Differential findings are research output, not infrastructure failure, so they do not automatically make the campaign command fail. Corpus regressions do return a nonzero exit status because an existing durable expectation has changed.

## Root and binary-safety rules

The campaign applies the same philosophy as the rest of PPC Lab:

1. target `image.path`/`image.data_path` inputs are resolved under a declared root before hashing or execution;
2. symlink/path escapes are rejected;
3. generated jobs may contain absolute paths only after those paths have passed containment;
4. corpus/evidence/triage artifacts preserve hashes and behavior, not target bytes by default;
5. `--dry-run` performs path/tool/capability validation without running guest code.

The campaign root is not a sandbox for hostile native tooling. It is a containment boundary for PPC Lab target inputs. Run PPC Lab itself with ordinary server isolation appropriate to your threat model.

## Protocols

v2.0 adds these machine-readable schemas:

- `ppc-lab-campaign-v1`
- `ppc-lab-campaign-state-v1`
- `ppc-lab-campaign-summary-v1`
- `ppc-lab-campaign-triage-summary-v1`

They are installed under `share/ppc-lab/schemas` and advertised by `ppc-lab capabilities --json`.

## Why this is v2.0

v1.x established the individual durable primitives: execution, worker transport, orchestration/fleet, evidence, trace analytics, corpus replay, differential triage, and guided exploration. v2.0 is the first layer that composes those primitives into an autonomous bounded research lifecycle. The C++ execution core remains focused and target-neutral; the autonomy lives in the standard-library tooling layer.

## v2.1 intelligence stage

Between exploration and corpus replay, v2.1 can run `ppc-lab-prioritize` and checkpoint `intelligence.json`. The optional `intelligence` manifest object controls the number of recommendations, plateau analysis, and transparent scoring weights. Triage eligibility is still controlled by `triage.select`; intelligence only orders the eligible set before the hard `max_triage_cases` limit is applied. See `CAMPAIGN_INTELLIGENCE.md`.
