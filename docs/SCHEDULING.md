# Campaign scheduling and resource governance

PPC Lab v2.2 adds `ppc-lab-schedule`, a dependency-free outer scheduler for running multiple existing `ppc-lab-campaign` manifests under shared resource policy. It does **not** redefine campaign execution. Each admitted item is launched through the installed campaign command and retains the campaign's own checkpoints, root containment, case/instruction budgets, corpus, triage, and evidence behavior.

## Why this layer exists

Long-lived PPC research servers eventually run unrelated projects at the same time. A single high-volume project should not monopolize every campaign slot, and an accidental campaign list should not silently consume an unlimited case budget. The scheduler therefore owns admission and process-level governance while the campaign layer remains the research unit.

## Manifest

```json
{
  "schema": "ppc-lab-scheduler-v1",
  "resources": {"max_concurrent": 4},
  "projects": [
    {"id": "classic-mac", "weight": 2, "max_concurrent": 3, "case_budget": 5000},
    {"id": "firmware", "weight": 1, "max_concurrent": 1, "case_budget": 1000}
  ],
  "campaigns": [
    {"id": "app-a", "project": "classic-mac", "manifest": "campaigns/app-a.json", "priority": 50, "reserve_cases": 500},
    {"id": "rom-b", "project": "firmware", "manifest": "campaigns/rom-b.json", "priority": 20, "reserve_cases": 250}
  ]
}
```

`resources.max_concurrent` is the global process cap. Project `max_concurrent` is an independent per-project cap. Project `weight` drives deterministic weighted fair-share selection between projects; `priority` orders campaigns *within* a project. This means a high-priority item can jump ahead of its project's own queue without letting that project starve every other project.

`case_budget` is an admission quota. A campaign's `reserve_cases` is charged when the campaign is admitted. If the reservation would exceed the project's quota, that campaign becomes `quota-blocked`. A quota-blocked decision is terminal for that scheduler state and remains terminal on `--resume`.

Project `wall_seconds` stops future admissions after already-consumed project process time reaches the budget. Campaign `wall_seconds` is a process-level kill limit for that one campaign. These are outer infrastructure budgets; they do not replace guest instruction limits or campaign case/wall budgets.

## Run and resume

```bash
ppc-lab-schedule scheduler.json --out /srv/ppc-scheduler/nightly
ppc-lab-schedule scheduler.json --out /srv/ppc-scheduler/nightly --resume
```

The scheduler writes atomic `state.json` and `summary.json` records. Resume requires the exact scheduler manifest SHA-256. Completed, failed, cancelled, and quota-blocked campaigns remain terminal. A process that was `running` when the scheduler died is returned to `pending`; if its campaign output already contains campaign state, the scheduler invokes `ppc-lab-campaign --resume`.

## Drain and cancellation

The scheduler intentionally uses filesystem control markers so supervisors, SSH sessions, shell scripts, and service managers can control it without another daemon/API.

- Create `<out>/DRAIN` to stop admitting new campaigns. Running campaigns finish, then the scheduler exits with status `drained`. Remove the marker and use `--resume` to continue pending work.
- Create `<out>/CANCEL` to terminate running campaigns and mark all pending campaigns cancelled.
- Create `<out>/cancel/<campaign-id>` to cancel one campaign before start or while running.

Cancellation is a scheduler/process decision, not a claim about target behavior. Campaign evidence already written before termination remains in that campaign's output directory.

## State and accounting

`ppc-lab-scheduler-state-v1` records project dispatch counts, reserved cases, elapsed process time, campaign attempts/status, and an append-only event list. `ppc-lab-scheduler-summary-v1` is the compact terminal/drained report.

Fair-share ordering uses project `dispatched / weight`; lower service ratio wins, with manifest project order as the deterministic tie break. Within the selected project, higher `priority` wins, then manifest order. Scheduling is therefore reproducible for the same manifest and completion sequence.

## Boundaries

The scheduler does not copy target binaries, interpret campaign manifests, bypass campaign root policy, or become a multi-user security boundary. It is process orchestration for trusted PPC Lab research hosts. Use normal OS users/containers/VMs for mutually untrusted tenants.

## Persistent control-plane operation

For a long-lived host with many scheduler manifests, v2.3 adds `ppc-lab-control` above this scheduler. It owns persistent scheduler-run queueing and operational supervision while this document's fair-share/quota semantics remain unchanged inside each admitted scheduler run. See [`CONTROL_PLANE.md`](CONTROL_PLANE.md).
