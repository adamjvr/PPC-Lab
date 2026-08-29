# LTS Security, Access Control & Auditability

PPC Lab 3.8 adds a dependency-free scoped authentication layer for the optional HTTP research service. It does not alter guest execution, target intake, or private-binary handling.

## Create an auth store and issue credentials

```bash
ppc-lab-security init /etc/ppc-lab/auth.json
ppc-lab-security issue /etc/ppc-lab/auth.json --role viewer --label dashboards
ppc-lab-security issue /etc/ppc-lab/auth.json --role runner --label ci-runner
ppc-lab-security issue /etc/ppc-lab/auth.json --role researcher --label analyst
```

The bearer token is printed once as `<token-id>.<secret>`. PPC Lab stores only a salted PBKDF2-SHA256 verifier. `list`, diagnostics, support bundles, backup, and release tooling never expose bearer secrets.

Roles are convenience presets: `viewer` gets `status:read` and `evidence:read`; `runner` gets `status:read` and `execute:run`; `researcher` gets all three; `admin` gets `*`. Explicit scopes may be added with repeated `--scope` arguments.

## Run the API with least privilege

```bash
ppc-lab-api --root /srv/ppc-lab/targets \
  --auth-store /etc/ppc-lab/auth.json \
  --audit-log /var/log/ppc-lab/audit.jsonl
```

Endpoint requirements are stable: health/capabilities require `status:read`, execution requires `execute:run`, and evidence endpoints require `evidence:read`. A presented credential that lacks the required scope receives HTTP 403; a missing credential receives 401.

Remote binds still require credentials unless the explicitly dangerous `--allow-unauthenticated-remote` override is used. Use TLS termination or an SSH tunnel for untrusted networks; PPC Lab's built-in HTTP server does not terminate TLS.

## Rotation and revocation

```bash
ppc-lab-security list /etc/ppc-lab/auth.json
ppc-lab-security rotate /etc/ppc-lab/auth.json TOKEN_ID
ppc-lab-security revoke /etc/ppc-lab/auth.json TOKEN_ID
```

Rotation revokes the old token and emits a new one with the same effective scopes. Revocation is immediate for subsequent HTTP requests because the API verifies against the store on every request.

## Audit integrity

When `--audit-log` is enabled, authorization decisions are appended as `ppc-lab-audit-record-v1` JSONL records. Each record contains the previous record hash and its own SHA-256 hash. Target bytes and bearer secrets are never recorded.

```bash
ppc-lab-security audit-verify /var/log/ppc-lab/audit.jsonl --json
```

The chain detects modification, deletion/reordering inside the retained log, or malformed records. Protect the log with normal OS permissions and external retention if stronger deletion resistance is required.
