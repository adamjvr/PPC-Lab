# Guided Exploration and Corpus Synthesis

PPC Lab v1.9 adds `ppc-lab-explore`, a deterministic input-space explorer above the stable `ppc-lab-job-v1` worker protocol. It is designed for reverse-engineering experiments where a small number of registers, memory writes, import bindings, or syscall returns control interesting behavior.

It is **not** a blind mutational fuzzer. Inputs are explicit, the run count is hard-bounded, and the default guided strategy only expands cases that discover new dynamic PCs or a previously unseen stable architectural outcome.

## Manifest

```json
{
  "schema": "ppc-lab-exploration-v1",
  "strategy": "guided",
  "max_cases": 64,
  "base_job": {
    "schema": "ppc-lab-job-v1",
    "image": {"path": "target.bin", "kind": "raw", "code_base": "0x10000000"},
    "execution": {"backend": "builtin", "entry": "0x10000000", "max_instructions": 100000},
    "registers": {"r3": 0}
  },
  "axes": [
    {"path": "registers.r3", "values": [0, 1, 2, 4, 8]},
    {"path": "writes_u32.0x40001000", "values": [0, 1, 4294967295]}
  ]
}
```

Supported mutation roots are deliberately limited to:

- `registers.*`
- `float_registers.*`
- `writes_u32.*`
- `writes_f32.*`
- `bindings.*`
- `syscall_returns.*`

Image paths, load addresses, entry points, backend choice, instruction limits, and other structural execution settings are not mutation axes. This prevents an exploration manifest from turning into an unbounded loader/configuration fuzzer.

## Guided strategy

`guided` starts from the base assignment and evaluates one-axis neighbors. A case becomes a parent only when it contributes at least one new dynamic PC or a new stable architectural outcome. Novel parents are then mutated again, allowing useful interactions to emerge without exhaustively evaluating every Cartesian combination.

```bash
ppc-lab-explore explore.json --out ./explore-run
```

The explorer forces tracing for each job but leaves the stable worker job protocol unchanged. Every evaluated case is written under `cases/`, and `summary.json` records overall coverage/behavior novelty and SHA-256 provenance for the target inputs.

## Cartesian strategy

Use `"strategy": "cartesian"` for deliberately small exhaustive domains. `max_cases` is still mandatory as a hard safety bound.

## Behavioral novelty

PPC Lab computes a SHA-256 fingerprint from backend-neutral architectural evidence: execution status, stop state, registers, CPU snapshot state, memory-region fingerprints, and requested dump fingerprints. Cosmetic transport output and backend labels do not define novelty.

## Corpus promotion

Successful novel cases can be promoted directly into the v1.7 behavioral corpus:

```bash
ppc-lab-explore explore.json \
  --out ./explore-run \
  --promote-corpus ./corpus
```

Promotion uses the existing `ppc-lab-corpus` contract. Target binaries are hashed and referenced, not copied into the corpus unless a separate explicit corpus workflow chooses to embed a redistributable fixture.

## Input/root safety

By default all target input files must resolve below the exploration manifest's directory. Use `--root /srv/private-targets` when the manifest belongs to a wider private target tree. The explorer verifies containment **before hashing input bytes**.

Results may be written elsewhere. Structural input paths cannot be mutated through exploration axes.

## Output contracts

v1.9 adds three stable JSON contracts:

- `ppc-lab-exploration-v1`
- `ppc-lab-exploration-case-v1`
- `ppc-lab-exploration-summary-v1`

These are installed with the rest of PPC Lab's schemas and advertised by `ppc-lab capabilities --json`.

## Campaign integration

For one exploration frontier, use `ppc-lab-explore` directly. When exploration should automatically flow into corpus replay, differential triage, and evidence publication, embed the unchanged `ppc-lab-exploration-v1` object inside a `ppc-lab-campaign-v1` manifest and run `ppc-lab-campaign`. The campaign layer resolves/contains structural target paths first and can tighten `max_cases`; it does not redefine exploration novelty semantics.

## Adaptive strategy (v2.1)

`strategy: "adaptive"` uses the same finite explicit axes as guided mode, but dynamically prefers mutation axes with stronger observed novelty/coverage yield. The optional `adaptive` object provides `plateau_window`, `plateau_novelty_rate`, and `min_cases`; after the minimum case count, a low-yield rolling window can end exploration before `max_cases`. The summary records per-axis yield plus the stop decision.
