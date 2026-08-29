# PPC Lab LTS deployment

`ppc-lab-deploy` turns an installed PPC Lab into a predictable Linux/systemd research service without introducing a package manager, container runtime, cloud service, or web framework dependency.

## Safety model

Deployment is **plan first** and does not invoke `systemctl`. The tool writes only declared configuration/service assets and directories. It never copies target binaries. The default API bind is loopback-only. If the API is exposed remotely, set `PPC_LAB_API_TOKEN` in `/etc/ppc-lab/ppc-lab.env` and terminate TLS in a trusted reverse proxy or use an SSH tunnel.

`uninstall` removes generated configuration/service assets but preserves research state and the target-input root. `--purge-state` must be explicit.

## Default layout

```text
/opt/ppc-lab             installed PPC Lab prefix
/etc/ppc-lab             deployment manifest + environment
/var/lib/ppc-lab         control/evidence/knowledge state
/var/cache/ppc-lab       disposable caches
/var/log/ppc-lab         operator logs
/srv/ppc-lab/targets     private target inputs (never copied by deploy)
/etc/systemd/system      ppc-lab-api.service / ppc-lab-control.service
```

## Plan

```bash
ppc-lab-deploy plan --service both --json
```

For an actual system install, normally install PPC Lab first with CMake and then:

```bash
sudo ppc-lab-deploy install --service both
sudo systemctl daemon-reload
sudo systemctl enable --now ppc-lab-control.service
sudo systemctl enable --now ppc-lab-api.service
```

Before enabling a remotely bound API, edit `/etc/ppc-lab/ppc-lab.env` and set a strong bearer token.

## Verify

```bash
sudo ppc-lab-deploy verify /etc/ppc-lab/deployment.json
```

Verification checks declared files, modes, hashes, directories, and rejects symlink substitution.

## Test/staging root

Maintainers and packaging systems can materialize the absolute deployment layout under a harmless staging directory:

```bash
ppc-lab-deploy install --dest-root /tmp/ppclab-root --json
ppc-lab-deploy verify /tmp/ppclab-root/etc/ppc-lab/deployment.json \
  --dest-root /tmp/ppclab-root --json
```

No root privileges or running systemd instance are needed for this mode.

## Uninstall

Preserve research state:

```bash
sudo ppc-lab-deploy uninstall /etc/ppc-lab/deployment.json
```

Destructive removal is intentionally explicit:

```bash
sudo ppc-lab-deploy uninstall /etc/ppc-lab/deployment.json --purge-state
```

Back up evidence, knowledge, control state, and private target inputs before using `--purge-state`.

## Disaster recovery

Before destructive deployment changes or `--purge-state`, create and verify a PPC Lab state backup. See [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md).

```bash
ppc-lab-backup create --state-root /var/lib/ppc-lab --out /backup/ppc-lab-state.zip
ppc-lab-backup verify /backup/ppc-lab-state.zip
```

The deployment's private target-input root is intentionally separate from this backup and must be protected independently.
