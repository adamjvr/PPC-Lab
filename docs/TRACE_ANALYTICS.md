# Trace intelligence and coverage analytics

PPC Lab v1.6 promotes existing `ppc-lab-trace-v1` instruction traces into higher-level dynamic reverse-engineering evidence without changing the execution-engine contract.

## Capture and analyze

```bash
ppc-lab-trace-capture --ppc-lab ppc-lab --json /tmp/run.trace.json -- \
  --image target.bin --entry-symbol interesting --backend builtin
ppc-lab-trace-analyze /tmp/run.trace.json \
  --json /tmp/run.analysis.json --dot /tmp/run.dynamic-cfg.dot
```

`ppc-lab-trace-analysis-v1` records total/unique PCs, instruction and mnemonic frequency, observed address span/covered bytes/density, symbol/function hotness, dynamically observed basic blocks, control-flow edges, and inferred link-branch calls. `--dot` exports the observed dynamic CFG in Graphviz DOT.

These are **dynamic** metrics: they describe the recorded execution, not every statically possible path in the target.

## Diff behavior

```bash
ppc-lab-trace-diff baseline.trace.json candidate.trace.json \
  --json /tmp/behavior.diff.json
```

`ppc-lab-trace-diff-v1` reports coverage Jaccard similarity, PCs unique to either run, per-PC/function execution-count deltas, and observed call-edge deltas. Add `--fail-on-diff` to make differences return exit status 1 for CI/regression gates.

## Persist and feed decompilers

Both new schemas begin with `ppc-lab-`, so the evidence store accepts them directly:

```bash
ppc-lab-evidence ingest /srv/ppc-evidence /tmp/run.analysis.json /tmp/behavior.diff.json
```

Analysis can also enrich existing neutral decompiler evidence:

```bash
python3 scripts/ppc_evidence_pack.py \
  --metadata /tmp/target.metadata.json \
  --trace /tmp/run.trace.json \
  --analysis /tmp/run.analysis.json \
  --json /tmp/target.evidence.json
```

This adds hot-block and observed-call annotations consumed by the existing Ghidra, IDA, and Binary Ninja adapters.

## Limits

- Calls are inferred from observed link branches and the following trace target.
- Symbol hotness depends on symbols supplied by the loader/profile; unnamed code is `<unknown>`.
- Indirect branches record only observed targets, not unseen possibilities.
- Per-instruction register/memory deltas are intentionally not duplicated here; snapshots/results remain state evidence.
