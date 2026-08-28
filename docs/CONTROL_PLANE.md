# Campaign control plane

PPC Lab v2.3 adds `ppc-lab-control`, a dependency-free persistent control plane above the v2.2 campaign scheduler. The scheduler remains the unit that applies project fair-share, priorities, quotas, and campaign process limits. The control plane adds the long-lived operational layer around scheduler runs: a durable queue, foreground supervision, live telemetry, pause/resume/drain/cancel controls, and append-only run history.

The control plane is intentionally a filesystem protocol and a foreground process. It does not require a database, message broker, web framework, or cloud service. Run it under the process supervisor you already trust (systemd, launchd, a container supervisor, SSH/tmux, or similar) if you want it to stay online indefinitely.

## Quick start

Initialize one durable server root:

```bash
ppc-lab-control init /srv/ppc-control
```

Submit existing `ppc-lab-scheduler-v1` manifests:

```bash
ppc-lab-control submit /srv/ppc-control nightly-classic-mac.json \
  --id classic-mac-nightly --priority 50

ppc-lab-control submit /srv/ppc-control firmware-sweep.json \
  --id firmware-sweep --priority 20
```

Run the foreground supervisor:

```bash
ppc-lab-control serve /srv/ppc-control --max-active 2
```

For CI/tests or one-shot queue draining, add `--until-idle`:

```bash
ppc-lab-control serve /srv/ppc-control --max-active 2 --until-idle
```

## Live status and telemetry

One-shot human status:

```bash
ppc-lab-control status /srv/ppc-control
```

Machine-readable status:

```bash
ppc-lab-control status /srv/ppc-control --json
```

Watch as NDJSON-like one-record-per-interval output:

```bash
ppc-lab-control status /srv/ppc-control --json --watch 1
```

The same latest snapshot is atomically written to `/srv/ppc-control/telemetry.json` using schema `ppc-lab-control-telemetry-v1`.

Telemetry includes:

- queue/terminal counts;
- pause/drain/global-cancel state;
- active scheduler process IDs and liveness;
- active-run uptime;
- scheduler campaign status counts;
- currently reported campaign subprocess PIDs;
- scheduler project/event counts;
- persistent history count.

This is operational telemetry, not guest behavior evidence. Guest/campaign evidence continues to live in the existing result/evidence/corpus layers.

## Pause, resume, drain, and cancellation

Pause new dispatch while allowing active scheduler runs to continue:

```bash
ppc-lab-control pause /srv/ppc-control
```

Resume dispatch. `resume` also clears a prior drain/global-cancel marker so the same root can be returned to service deliberately:

```bash
ppc-lab-control resume /srv/ppc-control
```

Gracefully drain: stop starting new queued items, allow active schedulers to finish, then let `serve` exit:

```bash
ppc-lab-control drain /srv/ppc-control
```

Cancel one queued/running scheduler run:

```bash
ppc-lab-control cancel /srv/ppc-control classic-mac-nightly
```

Cancel everything:

```bash
ppc-lab-control cancel /srv/ppc-control --all
```

A running-item cancellation is propagated through the scheduler's established `<scheduler-out>/CANCEL` marker rather than inventing a second campaign termination mechanism.

## Persistent queue ordering

Every submission receives a monotonically increasing sequence number, an integer priority, and the scheduler manifest SHA-256. The SHA-256 is rechecked immediately before dispatch; a manifest changed after submission is recorded as a failed queue item rather than executed under stale queue metadata. The control plane dispatches:

1. higher numeric priority first;
2. lower sequence number first for equal priority;
3. item ID as a final deterministic tie break.

Project fairness remains the responsibility of the v2.2 scheduler manifest inside each queue item. This separation is deliberate: control-plane priority decides which *scheduler run* enters service, while the scheduler decides how campaigns/projects share resources inside that admitted run.

## Filesystem layout

A control root looks like:

```text
/srv/ppc-control/
  control.json
  SERVER.lock
  telemetry.json
  PAUSE                  # optional marker
  DRAIN                  # optional marker
  CANCEL                 # optional marker
  queue/
    classic-mac-nightly.json
  runs/
    classic-mac-nightly/
      state.json          # scheduler state
      summary.json        # scheduler summary when available
  logs/
    classic-mac-nightly.stdout.log
    classic-mac-nightly.stderr.log
  history/
    history.ndjson
    classic-mac-nightly.json
```

Queue items use `ppc-lab-control-item-v1`. The root metadata uses `ppc-lab-control-v1`. Terminal history records use `ppc-lab-control-history-v1`.

All control-plane JSON updates use same-directory unique temporary files followed by `os.replace`, so concurrent status/supervisor writers do not share a temp filename and readers never need to consume a partially written JSON object.

## History

Terminal queue items are appended exactly once to `history/history.ndjson` and also receive a per-ID JSON record:

```bash
ppc-lab-control history /srv/ppc-control
ppc-lab-control history /srv/ppc-control --json --limit 20
```

History records preserve scheduler-manifest SHA-256, queue sequence/priority, attempts, timestamps, return code, output path, and the scheduler summary when one was produced. They do not copy target binaries.

## Restart and recovery semantics

The queue and run directories are durable. If the control process exits cleanly, active child schedulers are terminated by the signal handler and the next `serve` can retry a dead `running` item as `queued`; the scheduler is invoked with `--resume` whenever its output directory already contains scheduler state.

A hard supervisor death can leave a scheduler child process alive. On the next `serve`, a persisted `running` item whose recorded PID is still alive is changed to `orphaned` rather than being duplicated. This is intentionally conservative: the control plane refuses to launch a second copy when it cannot prove the first copy is dead. Use `ppc-lab-control cancel ROOT ITEM_ID` to terminate/close the orphan conservatively, then submit a new scheduler run if needed.

The v2.3 control plane is not a process-adoption system and does not claim to recover an arbitrary detached process handle across OS restarts.

## Single-supervisor lock

`serve` owns `SERVER.lock`. A second live supervisor is rejected. A stale lock whose PID no longer exists is replaced automatically. This is a local trusted-host coordination mechanism, not a distributed lock service.

## Security boundary

The control plane is intended for trusted research hosts and trusted scheduler manifests. It does not add authentication, tenant isolation, network exposure, privilege separation, or sandboxing. Use OS accounts, containers, VMs, SSH policy, and the existing PPC Lab root-containment features when isolation matters.

The control plane stores scheduler manifest paths/hashes and research status. It does not copy target binaries into its queue/history layer.

## Stable v2.3 contracts

The additive v2.3 schemas are:

- `ppc-lab-control-v1`
- `ppc-lab-control-item-v1`
- `ppc-lab-control-telemetry-v1`
- `ppc-lab-control-history-v1`
- `ppc-lab-control-history-record-v1`

Their meanings are additive across compatible 2.x releases. New optional fields may appear; incompatible field meanings require a new schema identifier.
