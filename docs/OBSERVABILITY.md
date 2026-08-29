# PPC Lab Observability and Capacity Planning

PPC Lab v3.7 adds a dependency-free observability layer for long-lived research servers. It is intentionally outside the execution engine: `ppc-lab-observe` reads stable control-plane JSON, collects portable host pressure metrics, stores immutable JSON observations, and derives health/capacity reports.

It never reads or copies PPC target binaries. The observability store contains JSON only.

## Initialize and sample

```bash
ppc-lab-observe init /var/lib/ppc-lab/observability

ppc-lab-observe sample /var/lib/ppc-lab/observability \
  --control-root /var/lib/ppc-lab/control \
  --slots 4 \
  --disk-path /var/lib/ppc-lab \
  --disk-path /var/cache/ppc-lab
```

Each sample records:

- control-plane queue depth, active count, pause/drain/cancel state, and terminal counts;
- history-derived service-time statistics for completed/failed/cancelled scheduler runs;
- configured concurrency slots when supplied;
- CPU count and normalized 1-minute load average when the host exposes it;
- Linux `MemAvailable`/`MemTotal` ratio when `/proc/meminfo` exists;
- free-space ratios for declared disk paths.

Samples are immutable files under `STORE/samples/`. A sample filename is derived from its timestamp and canonical-content SHA-256 prefix.

## Trend report

```bash
ppc-lab-observe report /var/lib/ppc-lab/observability --since-hours 24 --json
```

`ppc-lab-observability-report-v1` includes queue and active mean/p50/p95/max, queue-nonzero fraction, terminal deltas, completed jobs/hour, failure rate, host pressure summaries, median/p95 service time, theoretical capacity from the median service time, and estimated time to clear the current backlog.

Observed throughput is calculated only when the selected window spans nonzero time. Capacity estimates fall back to the supplied slot count plus median service time when observed throughput is unavailable.

## Health policy

The default policy warns on sustained queues, high failure rate, normalized load pressure, low available memory, low disk space, or a long estimated backlog-clear time. It is intentionally conservative and can be overridden by a JSON policy:

```json
{
  "schema": "ppc-lab-observability-policy-v1",
  "min_samples": 6,
  "queue_depth_warn": 8,
  "queue_depth_critical": 32,
  "failure_rate_warn": 0.05,
  "failure_rate_critical": 0.15,
  "disk_free_ratio_warn": 0.20,
  "disk_free_ratio_critical": 0.10
}
```

Run the check with:

```bash
ppc-lab-observe check /var/lib/ppc-lab/observability \
  --since-hours 24 \
  --policy /etc/ppc-lab/observability-policy.json \
  --json
```

Exit status is `0` for `ok` and `warning`, `1` for `critical`, and `2` for malformed input/tooling errors. This makes the command suitable for cron/systemd health checks without treating every warning as a service failure.

## Capacity planning

```bash
ppc-lab-observe capacity /var/lib/ppc-lab/observability \
  --since-hours 24 \
  --target-clear-hours 2 \
  --json
```

The capacity report estimates jobs/hour per slot from the most recent median scheduler-run service time and calculates the number of slots required to clear the **current** backlog within the requested target. It is not a forecasting model: it does not invent future arrival rates or assume that every campaign has identical work.

Use it as a sizing signal alongside observed throughput, not as a guarantee.

## Scheduling samples

PPC Lab deliberately does not introduce another daemon for metrics collection. Use the existing OS scheduler. A simple systemd timer or cron entry can run `ppc-lab-observe sample` every 1–5 minutes depending on the scale of the server.

The sample command is atomic and safe to run while the control plane is active. It invokes the public `ppc-lab-control status/history --json` contracts rather than opening or mutating queue state directly.

## LTS contract

v3.7 introduces observability API version `1` and these additive v3 LTS schemas:

- `ppc-lab-observability-store-v1`
- `ppc-lab-observation-v1`
- `ppc-lab-observability-report-v1`
- `ppc-lab-observability-policy-v1`
- `ppc-lab-observability-check-v1`
- `ppc-lab-capacity-report-v1`

The v3 same-major compatibility policy prevents future LTS releases from silently removing these installed schemas or the `ppc-lab-observe` command.
