# Campaign intelligence and prioritization

PPC Lab v2.1 adds a deterministic research-yield layer between exploration and differential triage. It does not use an opaque model and it does not relax campaign budgets. Every score is derived from recorded exploration evidence and every weight is explicit.

## Standalone prioritization

```bash
ppc-lab-prioritize ./explore-run --json ./priority.json --top 16
```

The report schema is `ppc-lab-priority-report-v1`. Cases are ranked by the sum of four components:

| Component | Default weight | Meaning |
|---|---:|---|
| `new_pc` | 10 | Number of PCs not observed before that case. |
| `behavior` | 25 | Stable architectural outcome was novel at discovery time. |
| `failure` | 40 | Guest execution did not complete successfully; useful for triage. |
| `pc_rarity` | 3 | Sum of inverse case-frequency for PCs observed by the case. |

All weights are non-negative and can be overridden on the command line or from a campaign `intelligence.weights` block. Ties are broken by case index, so identical inputs always produce identical rankings.

The report also aggregates every explored axis/value: case count, novelty rate, new-PC yield, and failure rate. This is intended to answer questions such as “is `registers.r3` producing useful branches while `registers.r7` is dead weight?” without manually reading case files.

## Plateau analysis

`--plateau-window N` and `--plateau-novelty-rate R` measure the last `N` exploration cases. A report marks the frontier `saturated` when the observed novelty rate is at or below `R`. This is advisory for ordinary guided/cartesian runs. Adaptive exploration can use the same idea during execution to stop early.

## Adaptive exploration

`ppc-lab-exploration-v1` now accepts:

```json
{
  "strategy": "adaptive",
  "max_cases": 256,
  "adaptive": {
    "plateau_window": 12,
    "plateau_novelty_rate": 0.08,
    "min_cases": 24
  }
}
```

Adaptive exploration keeps the same explicit finite value domains as guided exploration. It is not random fuzzing. After each executed mutation PPC Lab records per-axis attempts, novel cases, and new-PC yield. Candidate mutations are rescored using those observed yields, with an exploration prior that prevents untried axes from being starved. Only novel parents are expanded, exactly as in guided mode.

After at least `min_cases`, if the most recent `plateau_window` has a novelty rate less than or equal to `plateau_novelty_rate`, the run stops with `adaptive.stop_reason = "novelty-plateau"`. `max_cases` remains a hard ceiling; adaptive mode may simply leave some of that budget unused.

## Campaign integration

A v2.1 campaign can add:

```json
"intelligence": {
  "enabled": true,
  "top": 16,
  "plateau_window": 8,
  "plateau_novelty_rate": 0.125,
  "weights": {
    "new_pc": 10,
    "behavior": 25,
    "failure": 40,
    "pc_rarity": 3
  }
}
```

The campaign creates `intelligence.json` immediately after exploration and checkpoints an `intelligence` stage. Differential-triage eligibility (`triage.select`) is still applied first; eligible cases are then sorted by priority score and the hard `budgets.max_triage_cases` limit is applied. This changes ordering, not containment.

If the priority report detects a plateau, the final campaign findings include `exploration-saturated`. That is a normal research result and does not make the campaign fail. The intelligence JSON is also eligible for normal evidence-store publication.

## Reproducibility rules

- no random sampling is used;
- explicit input domains remain the source of all mutations;
- scoring weights and plateau thresholds are recorded in the priority report;
- case indices remain stable for a given exploration order;
- campaign resume still requires the exact manifest SHA-256 and PPC Lab engine version;
- target binaries remain external and are never copied by prioritization.
