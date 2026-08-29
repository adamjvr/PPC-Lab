# LTS Diagnostics and Support Bundles

PPC Lab v3.3 adds `ppc-lab-support` for target-neutral diagnostics. It is intended for bug reports, remote server support, and future target-driven maintenance without requiring someone to manually collect version strings, database checks, or scheduler state.

## Diagnose an installation

```bash
ppc-lab-support diagnose --json
```

To include persisted research state:

```bash
ppc-lab-support diagnose \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control \
  --json
```

The report checks the core executable/doctor path, installed companion-tool readiness, capability discovery, LTS compatibility declarations, persisted-state compatibility, evidence integrity, knowledge-graph integrity, and control-plane telemetry/recent failures when those roots are supplied.

The report intentionally omits usernames, hostnames, environment variables, network configuration, and target bytes.

## Create a support bundle

```bash
ppc-lab-support bundle \
  --evidence /srv/ppc-evidence \
  --knowledge /srv/ppc-knowledge \
  --control /srv/ppc-control \
  --log /var/log/ppc-lab-worker.log \
  --out ppc-lab-support.zip
```

A bundle may contain only:

```text
support-report.json
SUPPORT-MANIFEST.json
logs/*.txt
```

Target binaries, object files, database files, core dumps, arbitrary attachments, and unknown ZIP members are not allowed. Logs are optional, must be UTF-8 text, are bounded to 2 MiB each, and receive best-effort secret/root-path redaction before being archived.

The manifest records SHA-256 and size for every payload member and explicitly declares `target_binaries_included=false`.

## Verify before sharing

```bash
ppc-lab-support verify ppc-lab-support.zip --json
```

Verification rejects unexpected archive members, missing or malformed manifests, changed payload hashes/sizes, and malformed support reports. This gives maintainers a narrow, auditable support artifact rather than a generic archive mechanism.

## Privacy boundary

Redaction is defense in depth, not a guarantee that arbitrary prose contains no sensitive information. Review optional text logs before publishing a support bundle. PPC Lab never implicitly copies private target binaries into support artifacts.
