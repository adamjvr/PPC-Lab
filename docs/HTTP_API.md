# PPC Lab HTTP Research API

`ppc-lab-api` is a dependency-free HTTP transport for PPC Lab's stable worker
and evidence contracts. It exists for deployments where a process pipe, SSH
stream, or direct fleet controller is not the convenient integration boundary.
It is intentionally thin: execution still goes through `ppc-lab-worker`, and
evidence queries still go through `ppc-lab-evidence`.

## Security model

The default bind is `127.0.0.1:8765`. Keep that default when using an SSH
tunnel, local service supervisor, or TLS reverse proxy.

A non-loopback bind is rejected unless a bearer token is configured with
`--token` or `PPC_LAB_API_TOKEN`. `--allow-unauthenticated-remote` exists only
for isolated lab networks and tests and should be treated as dangerous.

**Bearer tokens do not encrypt HTTP.** For traffic crossing a machine boundary,
use an SSH tunnel, VPN/private transport, or a TLS reverse proxy. Do not expose
plain `ppc-lab-api` directly to the public internet.

The API inherits the worker's containment controls:

- `--root` restricts target binary/data inputs using resolved real paths;
- `--job-timeout` bounds each execution request;
- `--max-body` bounds JSON request bodies (1 MiB by default);
- evidence endpoints are read-only;
- target binaries are not returned or copied into the evidence store;
- no shell is used to construct worker/evidence commands.

## Start a local server

```bash
export PPC_LAB_API_TOKEN='replace-with-a-random-secret'
ppc-lab-api \
  --root /srv/ppc-work \
  --evidence-store /srv/ppc-evidence
```

The server prints a `ppc-lab-api-ready-v1` JSON line after binding. For service
supervisors/tests, `--write-ready FILE` atomically writes the same information.
Use `--port 0` to request an ephemeral port.

Without an evidence store, execution/capability endpoints still work and the
evidence endpoints are omitted from discovery.

## Authentication

When a token is configured, send:

```text
Authorization: Bearer <token>
```

Every endpoint, including health, requires the token. Comparisons use
constant-time `hmac.compare_digest`.

## Discovery and health

### `GET /v1`

Returns `ppc-lab-api-discovery-v1` with the engine version and enabled endpoint
set.

### `GET /v1/health`

Returns:

```json
{"schema":"ppc-lab-api-health-v1","ok":true,"version":"1.5.0"}
```

### `GET /v1/capabilities`

Returns the normal `ppc-lab-capabilities-v1` document plus:

```json
{
  "protocols": {"http_api": "ppc-lab-http-api-v1"},
  "api": {"evidence": true}
}
```

Clients should negotiate capabilities instead of assuming a backend or image
format exists on every server.

## Execute a job

### `POST /v1/run`

The request body is **exactly** a `ppc-lab-job-v1` document. There is no second
HTTP-specific execution schema.

```bash
curl -sS \
  -H "Authorization: Bearer $PPC_LAB_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @job.json \
  http://127.0.0.1:8765/v1/run
```

The response is exactly `ppc-lab-worker-response-v1`.

A valid guest stop/failure is still HTTP `200`: the transport and worker
protocol succeeded, and the caller must inspect `ok`, `exit_code`, `error`, and
`result.stop_reason`. HTTP 4xx/5xx statuses are reserved for authentication,
transport, request, or server failures.

## Evidence endpoints

These exist only when `--evidence-store` points to an initialized evidence
store.

### `POST /v1/evidence/query`

Accepts a small JSON object corresponding to the indexed query filters:

```json
{
  "engine_version": "1.5.0",
  "backend": "builtin-ppc32be",
  "stop_reason": "return",
  "host": "worker-a",
  "name": "constructor",
  "cache_key": "ab12",
  "input_sha256": "8f31d9",
  "ok": true,
  "limit": 50,
  "oldest": false
}
```

Returns `ppc-lab-evidence-query-v1`.

### `GET /v1/evidence/report`

Returns `ppc-lab-evidence-report-v1`.

### `GET /v1/evidence/artifacts/{id-or-sha-prefix}`

Returns the canonical stored evidence JSON for one artifact. The identifier is
restricted to an integer id or hexadecimal SHA-256 prefix.

There is intentionally no HTTP evidence-ingest endpoint in v1.5. Publication
continues to happen through trusted local orchestration/fleet processes. This
keeps the network-facing API read-only with respect to the evidence store.

## SSH tunnel deployment

On the server:

```bash
PPC_LAB_API_TOKEN="$TOKEN" \
ppc-lab-api --root /srv/ppc-work --evidence-store /srv/ppc-evidence
```

On the client:

```bash
ssh -N -L 8765:127.0.0.1:8765 ppc-server
```

Then use `http://127.0.0.1:8765` locally. The HTTP traffic remains inside the
SSH tunnel.

## TLS reverse proxy deployment

Keep PPC Lab bound to loopback and let a maintained reverse proxy terminate
TLS, enforce network policy, rate limits, and any organization-specific auth.
PPC Lab deliberately does not embed a TLS implementation or web framework.

## Stability

`ppc-lab-http-api-v1` is additive within the v1 line. Existing endpoints and
worker/evidence payload contracts will not be repurposed incompatibly. New
optional response fields/endpoints may be added. A future breaking transport
contract requires a new protocol name.
