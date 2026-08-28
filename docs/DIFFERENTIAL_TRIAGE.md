# Differential triage

`ppc-lab-triage` turns an execution disagreement into a small, reviewable research artifact. It is intentionally a standard-library tool above PPC Lab's existing `ppc-lab-trace-v1`, `ppc-lab-job-v1`, and worker response contracts; the execution core does not gain target-specific comparison logic.

## Compare existing traces

```bash
ppc-lab-triage compare baseline.trace.json candidate.trace.json \
  --left-snapshot baseline.snapshot.json \
  --right-snapshot candidate.snapshot.json \
  --json triage.json \
  --bundle triage-bundle \
  --fail-on-diff
```

The report records:

- exact trace equality;
- common-prefix instruction/event count;
- first divergent PC and instruction word;
- a classification (`control-flow`, `instruction-bytes`, `trace-length`, `dynamic-sequence`, `state-only`, or `worker-outcome`);
- a bounded event window around the divergence;
- a later trace resynchronization point when one can be identified;
- architectural snapshot differences, with backend-name noise ignored.

Trace alignment uses `(PC, instruction-word)` signatures. Symbols and rendered disassembly are treated as annotations so a symbolizer wording change does not create a false execution divergence.

## Run the same job twice

```bash
ppc-lab-triage run job.json \
  --left-ppc-lab /opt/ppc-lab-old/bin/ppc-lab \
  --right-ppc-lab /opt/ppc-lab-new/bin/ppc-lab \
  --left-worker /opt/ppc-lab-old/bin/ppc-lab-worker \
  --right-worker /opt/ppc-lab-new/bin/ppc-lab-worker \
  --left-backend builtin \
  --right-backend auto \
  --root /srv/ppc-targets \
  --bundle ./triage-001
```

The job is copied in memory, tracing is enabled on both sides, and only the requested backend is changed. Both executions still pass through the stable worker contract, including filesystem and wall-clock containment.

This supports three common comparisons without changing the project job format:

1. builtin vs Unicorn in one PPC Lab build;
2. old PPC Lab vs new PPC Lab using the same backend;
3. old/backend-A vs new/backend-B when investigating a compatibility regression.

## Triage bundle

A `--bundle DIR` contains:

```text
manifest.json
triage.json
left.trace.json
right.trace.json
left.response.json      # live-run mode
right.response.json     # live-run mode
repro.job.json          # live-run mode
README.md
```

The reduced repro job preserves the original job but caps `execution.max_instructions` shortly after the common-prefix boundary. It is a bounded reproduction aid, not a claim that the binary/input itself has been minimized.

PPC Lab does **not** copy target binaries into a triage bundle. Live-run reports record SHA-256 and size for referenced code/data inputs so private bytes can remain in project-owned storage while the triage evidence stays portable.

## Exit status

Without `--fail-on-diff`, a successfully generated report exits 0 whether the traces match or not. With `--fail-on-diff`, a behavioral difference exits 1, which is useful in CI. Invalid input/protocol/tooling failures exit 2.

## Stability

The machine-readable report schema is `ppc-lab-differential-triage-v1`; bundle manifests use `ppc-lab-triage-bundle-v1`. New optional fields may be added compatibly in v1.x, but existing required meanings are stable.
