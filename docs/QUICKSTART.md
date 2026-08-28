# Quick start

## 1. Build and verify

macOS/Linux:

```bash
./Tools/verify.command
```

The release binary is normally:

```bash
./build/release/ppc-lab
```

Sanity check:

```bash
./build/release/ppc-lab selftest --backend builtin
```

## 2. Diagnose the build and identify a native PPC image

```bash
./build/release/ppc-lab doctor
./build/release/ppc-lab analyze /path/to/target
```

Supported native intake:

- ELF32 big-endian PowerPC (`ET_EXEC`, `ET_DYN`, `ET_REL`);
- 32-bit big-endian PowerPC Mach-O, thin or fat;
- PowerPC PEF/CFM.

If the target is not a native supported container but you already have raw
relocated code, use `--code` as before.

## 3. See symbols when available

```bash
./build/release/ppc-lab symbols /path/to/target
```

For relocatable objects this is often the fastest way to choose a function for
an isolated experiment.

## 4. Disassemble a small region

```bash
./build/release/ppc-lab disasm --image /path/to/target --count 32
```

Override the start address when useful:

```bash
./build/release/ppc-lab disasm --image /path/to/target --start 0x00104560 --count 64
```

## 5. Execute an entry or function

Native default entry:

```bash
./build/release/ppc-lab run --image /path/to/target --backend builtin
```

Named function in a relocatable/shared image:

```bash
./build/release/ppc-lab run \
  --image module.o \
  --image-base 0x12000000 \
  --entry-symbol process \
  --set r3=5
```

Numeric function entry:

```bash
./build/release/ppc-lab run \
  --image target.macho \
  --entry 0x00104560 \
  --set r3=0x40010000
```

PEF default main:

```bash
./build/release/ppc-lab run \
  --image application.pef \
  --image-base 0x11000000
```

## 6. Bind an unresolved external only when execution needs it

If relocation/loading reports a missing symbol:

```bash
./build/release/ppc-lab run \
  --image module.o \
  --entry-symbol process \
  --bind memcpy=0x30000100
```

If that address should also behave like one of PPC Lab's reusable runtime stubs:

```bash
--bind memcpy=0x30000100 --stub memcpy@0x30000100
```

Or let a reusable personality bind the imports it understands:

```bash
python3 scripts/ppc_runtime_call.py \
  --runtime runtimes/libc-posix-minimal.json \
  --image module.o -- --entry-symbol process --backend builtin
```

Do not pre-stub everything. Let execution tell you what is actually required.

## 7. Capture deterministic evidence

```bash
./build/release/ppc-lab call \
  --elf target.elf \
  --entry 0x00104560 \
  --set r3=5 \
  --dump 0x40010000:128 \
  --trace-range 0x00104560:0x00104680 \
  --json /tmp/ppc-result.json \
  --snapshot /tmp/ppc-state.json
```

Inspect the result:

```bash
python3 scripts/ppc_result_inspect.py /tmp/ppc-result.json
```

Compare full state with `python3 scripts/ppc_snapshot_diff.py A.json B.json`. For repeated parameter studies, use `ppc_lab_batch.py`; for A/B execution, use `ppc_differential.py`.

## 8. Turn a successful experiment into a profile

Once the experiment answers a useful research question, put only the reusable
metadata/script/expected hashes under `profiles/<target>/`. Keep proprietary
binary bytes external.

See [`ADDING_A_TARGET.md`](ADDING_A_TARGET.md).

## 9. Submit the same work as a server job

For automation that should not depend on CLI spelling, use the v1 worker protocol:

```bash
ppc-lab-worker --ppc-lab ./build/release/ppc-lab --root "$PWD" run job.json
```

For a persistent pipe (including over SSH), use NDJSON stream mode:

```bash
ppc-lab-worker --root /srv/ppc-work stream
```

See [`WORKER_PROTOCOL.md`](WORKER_PROTOCOL.md).

## 10. Index useful server/fleet evidence

For long-lived research, put completed PPC Lab JSON output into a central evidence store instead of relying on remembered result-directory names:

```bash
ppc-lab-evidence init /srv/ppc-evidence
ppc-lab-evidence ingest /srv/ppc-evidence /srv/results/run-001
ppc-lab-evidence query /srv/ppc-evidence --input-sha256 <target-sha-prefix> --ok yes
```

Or add `--evidence-store /srv/ppc-evidence` to `ppc-lab-orchestrate`/`ppc-lab-fleet`. The store indexes JSON evidence and input hashes; it does not copy target binaries. See [`EVIDENCE_STORE.md`](EVIDENCE_STORE.md).


## Run a bounded autonomous campaign

Once a reverse-engineering question has explicit input domains, use `ppc-lab-campaign` instead of hand-running the explorer/corpus/triage/evidence loop:

```bash
ppc-lab-campaign campaign.json --out ./runs/campaign-001 --dry-run
ppc-lab-campaign campaign.json --out ./runs/campaign-001
```

If the server process is interrupted, rerun the exact same manifest/engine with `--resume`. See `CAMPAIGNS.md` for the manifest and checkpoint contract.
