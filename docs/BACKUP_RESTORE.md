# PPC Lab LTS backup, restore, and disaster recovery

`ppc-lab-backup` is the v3.5 LTS disaster-recovery surface for persistent PPC Lab server state. It is dependency-free and deliberately narrower than a general filesystem backup utility.

## What is protected

A backup may contain these persistent components under the deployment state root:

- `evidence/` — a transactionally consistent `evidence.sqlite3` snapshot plus exactly the immutable canonical JSON objects referenced by that database;
- `knowledge/` — a transactionally consistent `knowledge.sqlite3` snapshot;
- `control/` — persistent `control.json`, queue, history, run-state JSON/NDJSON, and bounded text state used to resume/understand scheduled work.

The default deployment root is `/var/lib/ppc-lab`.

## What is intentionally not protected

The backup format is **not** a target-binary archive. It never traverses or copies `/srv/ppc-lab/targets` and does not copy:

- private PPC executables, firmware, ROMs, or other target inputs;
- `/etc/ppc-lab/ppc-lab.env` or bearer tokens;
- cache directories;
- general operator logs;
- control-plane locks, telemetry, PAUSE/DRAIN/CANCEL markers;
- arbitrary binary files placed inside control run directories.

If `--deployment /etc/ppc-lab/deployment.json` is supplied, only that public deployment manifest is included. The secret environment file is never read.

Keep private targets backed up using the storage policy appropriate for those materials. PPC Lab records their SHA-256 identities so restored research state can be paired with separately restored inputs.

## Create a backup

For the safest control-plane snapshot, drain or stop `ppc-lab-control` first:

```bash
sudo systemctl stop ppc-lab-control.service
ppc-lab-backup create \
  --state-root /var/lib/ppc-lab \
  --deployment /etc/ppc-lab/deployment.json \
  --out /backup/ppc-lab-state.zip
ppc-lab-backup verify /backup/ppc-lab-state.zip
sudo systemctl start ppc-lab-control.service
```

Evidence and knowledge SQLite files use SQLite's online backup API, so their database snapshots are internally consistent even if readers are active. The control plane is filesystem state rather than one transaction; an active control supervisor is therefore rejected by default. `--allow-live-control` exists for emergency snapshots, but a drained/stopped control plane is the normal recovery-grade procedure.

## Verify and inspect

```bash
ppc-lab-backup verify /backup/ppc-lab-state.zip --json
ppc-lab-backup inspect /backup/ppc-lab-state.zip --json
```

Verification checks:

- the `ppc-lab-backup-v1` manifest;
- the exact allowed archive member set;
- path traversal and symlink rejection;
- SHA-256 and byte length of every payload;
- evidence/knowledge SQLite `PRAGMA integrity_check`;
- control-plane schema validity;
- explicit policy declarations that target binaries and API secrets were not copied.

Unexpected ZIP members fail verification rather than being ignored.

## Restore after a failure

Install the same or a compatible PPC Lab v3 LTS build first, then verify the backup before restore:

```bash
ppc-lab-backup verify /backup/ppc-lab-state.zip
sudo systemctl stop ppc-lab-api.service ppc-lab-control.service
sudo ppc-lab-backup restore /backup/ppc-lab-state.zip \
  --state-root /var/lib/ppc-lab
ppc-lab-compat state \
  --evidence /var/lib/ppc-lab/evidence \
  --knowledge /var/lib/ppc-lab/knowledge \
  --control /var/lib/ppc-lab/control
sudo systemctl start ppc-lab-control.service ppc-lab-api.service
```

Restore refuses to overwrite any protected component that already exists. This makes an accidental restore onto a live server fail safely.

If replacement is intentional:

```bash
sudo ppc-lab-backup restore /backup/ppc-lab-state.zip \
  --state-root /var/lib/ppc-lab \
  --force
```

Before replacing components, `--force` moves the existing component directories into a `.pre-restore-<timestamp>-<pid>` safety directory under the state root. That safety copy is not automatically deleted.

If a backup contains public deployment metadata, it can also be recovered to a review location:

```bash
ppc-lab-backup restore ppc-lab-state.zip \
  --state-root /var/lib/ppc-lab \
  --deployment-out /tmp/ppc-lab-deployment.restored.json
```

Review deployment metadata and recreate secrets separately; PPC Lab deliberately cannot recover an API token it never archived.

## Recovery drill

A recovery process that has never been tested is not a recovery process. Periodically restore a verified backup into a staging root and run the platform checks:

```bash
rm -rf /tmp/ppclab-dr
ppc-lab-backup restore ppc-lab-state.zip --state-root /tmp/ppclab-dr
ppc-lab-compat state \
  --evidence /tmp/ppclab-dr/evidence \
  --knowledge /tmp/ppclab-dr/knowledge \
  --control /tmp/ppclab-dr/control --json
```

This validates both archive integrity and the ability of the installed LTS release to understand the restored state.

## Backup retention

PPC Lab does not prescribe a cloud provider or retention service. For a research server, a practical policy is to keep multiple dated verified state backups on storage independent of the server and separately protect the private target corpus. Record the ZIP SHA-256 alongside each backup.

The stable formats are:

- `ppc-lab-backup-v1`
- `ppc-lab-backup-report-v1`

They are part of the v3 LTS compatibility surface.
