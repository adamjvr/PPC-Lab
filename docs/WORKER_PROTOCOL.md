# Server-side worker protocol

PPC Lab v1.1 adds a transport-neutral execution boundary for long-lived reverse-engineering infrastructure. The goal is simple: client projects should submit a stable JSON job instead of knowing PPC Lab's command-line spelling.

The worker is `ppc-lab-worker`, installed with PPC Lab and implemented with the Python standard library only. It deliberately does **not** embed an HTTP server, message broker, database, scheduler, authentication system, or cloud SDK. Those are deployment policy. The protocol can travel over a local pipe, SSH, CI runner, container exec, queue consumer, or a future service without changing the research job format.

## Protocols

- request schema: `ppc-lab-job-v1`
- response schema: `ppc-lab-worker-response-v1`
- streaming transport: newline-delimited JSON (NDJSON), one request and one response per line
- result payload: the existing `ppc-lab-result-v1`
- snapshot payload: the existing `ppc-lab-snapshot-v1`

Machine-readable JSON Schema documents live in `schemas/`.

## One job

```bash
ppc-lab-worker --root /srv/ppc-work run /srv/ppc-work/jobs/test.json
```

Or over stdin:

```bash
cat job.json | ppc-lab-worker --root "$PWD" run -
```

The response is one JSON object on stdout. A successful response contains the deterministic result and full snapshot inline.

## Long-lived stream

```bash
ppc-lab-worker --root /srv/ppc-work stream
```

Then send one compact JSON job per line. The worker emits exactly one compact JSON response per non-empty input line and flushes immediately. An execution failure does not terminate the stream. Malformed transport JSON is reported as a response and causes the worker to exit with status 2 when stdin closes.

That behavior makes the worker safe to wrap with SSH:

```bash
ssh ppc-host 'ppc-lab-worker --root /srv/ppc-work stream'
```

A local research client can keep the SSH process open and exchange NDJSON jobs without implementing a network daemon in PPC Lab.

## Job shape

Minimal native-container job:

```json
{
  "schema": "ppc-lab-job-v1",
  "id": "probe-42",
  "image": {"path": "targets/app.pef", "kind": "auto"},
  "execution": {"backend": "builtin", "entry_symbol": "RenderBlock"},
  "registers": {"r3": "0x40010000"},
  "dumps": [{"address": "0x40010000", "size": 128}]
}
```

Raw images use `"kind": "raw"` and normally specify `image.code_base` plus `execution.entry`.

Numeric fields may be JSON integers or PPC Lab numeric strings such as `"0x10000000"`. Floating-point register/write values may be JSON numbers or numeric strings.

The worker supports the stable execution controls already exposed by `ppc-lab run`:

- image kind and mapping bases/sizes;
- backend, entry/entry-symbol, TOC and CFM transition vector;
- instruction limit, return/import addresses, trace and trace-range;
- GPR/FPR initialization;
- `u32`/`f32` memory initialization;
- symbol bindings and import stubs;
- deterministic syscall return mappings and trap policy;
- memory dumps.

See `schemas/ppc-lab-job-v1.schema.json` for the complete v1 contract.

## Response shape

```json
{
  "schema": "ppc-lab-worker-response-v1",
  "id": "probe-42",
  "ok": true,
  "exit_code": 0,
  "timed_out": false,
  "result": {"schema": "ppc-lab-result-v1"},
  "snapshot": {"schema": "ppc-lab-snapshot-v1"},
  "stdout": "..."
}
```

`ok` means the PPC execution returned with CLI exit status 0. Unsupported instructions, traps, syscalls, memory faults, instruction limits, and configuration failures are still valid worker responses; they set `ok` false and preserve the PPC Lab result when one was produced.

## Filesystem containment

For server use, pass `--root DIRECTORY`. Every job input (`image.path` and optional `image.data_path`) must resolve to a regular file inside that tree. Symlink resolution occurs before the containment check, so a symlink cannot escape the root.

`--root` is a filesystem containment feature, **not an authentication boundary or OS sandbox**. Run untrusted jobs under an appropriately restricted account/container/VM according to the deployment threat model.

## Wall-clock containment

`--timeout SECONDS` defaults to 60 seconds per job. This is independent of PPC Lab's deterministic guest `max_instructions` limit. A server deployment should normally set both:

- `execution.max_instructions` limits guest work reproducibly;
- worker `--timeout` protects the host against backend/tool hangs.

## Debugging

`--expose-command` includes the local `ppc-lab` argv in responses. It is off by default because filesystem paths and target-specific bindings may be sensitive in shared infrastructure.

The stable API is the JSON job/response contract, not the generated argv.

## v1.2 stdin base-directory control

`--base-dir DIRECTORY` sets the path-resolution base for jobs arriving through stdin or NDJSON. It is separate from `--root`: `--base-dir` answers "what does this relative path mean?", while `--root` answers "is the resolved file allowed?".

The parallel orchestrator uses this separation to preserve manifest/job-relative paths while retaining strict root containment. See `ORCHESTRATION.md`.
