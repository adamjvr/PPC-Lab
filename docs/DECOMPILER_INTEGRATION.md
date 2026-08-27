# Decompiler integration

PPC Lab v0.4 uses a decompiler-neutral evidence format instead of making the
execution engine depend on one reverse-engineering suite.

## Capture evidence

1. Export normalized loader metadata:

```bash
./build/release/ppc-lab metadata target.elf > /tmp/target.metadata.json
```

2. Capture a symbolized execution trace:

```bash
python3 scripts/ppc_trace_capture.py \
  --ppc-lab ./build/release/ppc-lab \
  --json /tmp/target.trace.json -- \
  --elf target.elf --entry-symbol interesting --backend builtin
```

3. Optionally capture a full state snapshot with the matching `call`.

4. Pack the evidence:

```bash
python3 scripts/ppc_evidence_pack.py \
  --metadata /tmp/target.metadata.json \
  --snapshot /tmp/target.snapshot.json \
  --trace /tmp/target.trace.json \
  --json /tmp/target.evidence.json
```

The result is `ppc-lab-evidence-v1`: normalized symbols plus address-based
behavioral annotations. Trace annotations include execution counts and decoded
instructions; snapshot annotations identify the stop point and run summary.

## Ghidra

Run `integrations/ghidra/PpcLabImportEvidence.py` from Ghidra's Script Manager.
It asks for an evidence JSON file, creates labels for defined symbols where
possible, and appends PPC Lab behavioral evidence as EOL comments.

## IDA

Load `integrations/ida/ppc_lab_import_evidence.py` in IDAPython and call:

```python
import_ppc_lab_evidence('/tmp/target.evidence.json')
```

## Binary Ninja

Load `integrations/binaryninja/ppc_lab_import_evidence.py` and call:

```python
import_ppc_lab_evidence(bv, '/tmp/target.evidence.json')
```

The adapters are deliberately thin. PPC Lab owns evidence production and the
neutral schema; decompiler scripts only apply labels/comments. This makes the
research data portable even if individual decompiler APIs change.
