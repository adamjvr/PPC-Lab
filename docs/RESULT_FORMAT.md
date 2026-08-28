# PPC Lab result format

`ppc-lab call --json FILE` writes a stable, machine-readable execution record. The current schema identifier is:

```json
"schema": "ppc-lab-result-v1"
```

The schema is intentionally small so it can be consumed by shell/Python tooling and archived as a regression artifact.

## Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Result schema identifier. |
| `backend` | string | Backend name that actually executed the call. |
| `stop_reason` | string | Normal return or the reason execution stopped. |
| `instructions` | integer | Number of executed instructions. |
| `pc` | hex string | Program counter at stop. |
| `instruction` | hex string | Current/offending instruction word when meaningful. |
| `registers` | object | `r0` through `r31` as 32-bit hex strings. |
| `lr` | hex string | Link register. |
| `ctr` | hex string | Count register. |
| `cr` | hex string | Condition register. |
| `dumps` | array | Requested deterministic memory captures. |

## Dump object

Each `--dump ADDRESS:SIZE` produces one object:

```json
{
  "address": "0x40010000",
  "size": 128,
  "fnv1a64": "0x418c9e14a76a422e",
  "hex": "00 00 00 00 ..."
}
```

`fnv1a64` is intended as a compact regression fingerprint, not a cryptographic integrity mechanism. Use SHA-256 externally when cryptographic file integrity matters.

If a requested range is unreadable, the human/JSON output reports that condition rather than inventing bytes.

## Recommended regression record

For a useful long-lived behavioral fixture, record at least:

- exact target/version identification;
- external target file hashes outside the repository when redistribution is prohibited;
- entry point or transition-vector address;
- TOC/r2 value when applicable;
- initial relevant GPR/FPR state;
- deterministic memory initialization;
- target import bindings;
- instruction limit;
- stop reason;
- instruction count;
- relevant memory-dump FNV fingerprints;
- any byte/float comparison results.

## Comparison helper

`compare_ppc_dump.py` compares a selected PPC Lab dump against a raw reference file.

Exact bytes:

```bash
python3 scripts/compare_ppc_dump.py \
  --ppc /tmp/result.json \
  --reference /tmp/reference.bin \
  --mode bytes
```

Float32 comparison:

```bash
python3 scripts/compare_ppc_dump.py \
  --ppc /tmp/result.json \
  --reference /tmp/reference-f32.bin \
  --mode float32 \
  --reference-endian le
```

The float32 report includes counts, first bitwise difference, RMS error, and maximum absolute error.

## Compatibility policy

Within a `*-v1` schema, fields should be additive when practical. A breaking format change should use a new schema identifier instead of silently changing the meaning of existing fields.


## Rich state snapshots (v0.4)

`--json` remains the compact backward-compatible execution result. Use
`--snapshot FILE` when a regression needs complete CPU state, region
fingerprints, loaded symbols, and requested dumps. The snapshot schema is
`ppc-lab-snapshot-v1`; see [`SNAPSHOTS.md`](SNAPSHOTS.md).

Normalized loader metadata and decompiler evidence intentionally use separate
schemas (`ppc-lab-metadata-v1` and `ppc-lab-evidence-v1`) so execution-result
compatibility is not coupled to external-tool integration.

## Long-lived evidence indexing (v1.4)

Execution/result schemas remain independent of the v1.4 evidence index. `ppc-lab-evidence` stores canonical copies of existing `ppc-lab-*` JSON documents and extracts query fields without changing the original document semantics. See [`EVIDENCE_STORE.md`](EVIDENCE_STORE.md).

