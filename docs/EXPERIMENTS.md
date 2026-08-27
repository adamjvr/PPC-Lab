# Batch experiments and differential execution

PPC Lab v0.4 treats a repeatable experiment as data. The runner scripts use JSON
only and have no PyYAML or framework dependency.

## Batch / parameter sweeps

Manifest schema: `ppc-lab-experiment-v1`.

```json
{
  "schema": "ppc-lab-experiment-v1",
  "base_args": [
    "--elf", "target.elf",
    "--entry-symbol", "filter",
    "--backend", "builtin",
    "--dump", "0x40010000:128"
  ],
  "cases": [
    {"name": "zero", "args": ["--set", "r3=0"]},
    {"name": "one", "args": ["--set", "r3=1"]}
  ],
  "sweep": {
    "r4": ["0", "1", "2", "4", "8"]
  }
}
```

Run it:

```bash
python3 scripts/ppc_lab_batch.py experiment.json \
  --ppc-lab ./build/release/ppc-lab \
  --out results/filter-sweep
```

Each case receives its own snapshot. `summary.json` records command lines,
parameters, stdout/stderr, exit status, and snapshot filenames.

## Differential execution

Manifest schema: `ppc-lab-differential-v1`.

```json
{
  "schema": "ppc-lab-differential-v1",
  "base_args": ["--elf", "target.elf", "--entry-symbol", "foo", "--set", "r3=7"],
  "left_args":  ["--backend", "builtin"],
  "right_args": ["--backend", "unicorn"]
}
```

```bash
python3 scripts/ppc_differential.py diff.json --ppc-lab ./build/release/ppc-lab
```

The two runs are snapshotted and compared deterministically. The same mechanism
can compare two image bases, runtime bindings, recovered implementations, or
parameterizations—not only execution backends.
