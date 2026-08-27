# Deterministic snapshots and state comparison

`ppc-lab call --snapshot FILE` writes `ppc-lab-snapshot-v1`. It is the canonical
v0.4 behavioral checkpoint format.

A snapshot records:

- backend, stop reason, stop PC/instruction, instruction count, message;
- all 32 GPRs;
- all 32 FPRs as exact 64-bit bit patterns;
- LR, CTR, CR, XER, and FPSCR;
- every mapped memory region's name, base, size, permissions, and FNV-1a64
  fingerprint;
- loaded image symbols;
- every explicitly requested `--dump`, including bytes and fingerprint.

The snapshot intentionally fingerprints full mapped regions rather than dumping
all region bytes into JSON. Add a targeted `--dump` when exact changed bytes are
part of the experiment.

Compare snapshots:

```bash
python3 scripts/ppc_snapshot_diff.py run-a.json run-b.json
```

For backend comparisons where only the backend name should differ:

```bash
python3 scripts/ppc_snapshot_diff.py a.json b.json --ignore-backend
```

Exit code is zero when the compared state is equal and nonzero when behavioral
state differs.
