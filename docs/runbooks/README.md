# Runbooks

Short, copy-paste procedures for when something breaks. Every alert on your phone ends
with a `runbook:` link to one of these pages.

## Start here, every time

```sh
cd ~/development/github.com/home-server
bin/health          # read-only; ~1 s. Each FAIL/WARN names the page to open.
```

If you can't get a shell on eris at all, go to [disaster-recovery.md](disaster-recovery.md).

| Symptom / alert | Page |
|---|---|
| A container is down, unhealthy, looping, OOM-killed | [containers.md](containers.md) |
| A website is down or slow, cert expiring, router/NAS/internet ping failing | [service-down.md](service-down.md) |
| Disk, memory, CPU, GPU, reboot | [host.md](host.md) |
| NAS shares missing or stale, Unraid disk/parity alerts (ntfy topic `unraid`) | [nas.md](nas.md) |
| Backup failed, job container missing, **restoring anything** | [backups.md](backups.md) |
| No alerts arriving, Prometheus/Grafana broken, `TargetDown` | [monitoring.md](monitoring.md) |
| eris dead, NAS dead, flash drive dead, house gone | [disaster-recovery.md](disaster-recovery.md) |

## Where alerts come from

| Source | ntfy topic | What |
|---|---|---|
| Prometheus → Alertmanager | `home_alerts` | Containers, endpoints, host, NAS mounts |
| Unraid notifications | `unraid` | Disk SMART/temps, array errors, parity |
| borgmatic, offsite-backup, nas-watchdog | `unraid` | Backup failures, mount recoveries |
| NAS borg freshness check (09:00) | `unraid` | Borg repo not written for 30 h |
| Ofelia `healthcheck` → healthchecks.io (every 5 min) | healthchecks.io email/app | eris, Docker or Ofelia completely down |
| Weekly audit (Sun 08:30) | `unraid` | Claude's summary of the week |

## Ground rules

- **Check before you change.** `bin/health` and the page's "Check" step first.
- **Don't run `docker system prune` or `docker container prune`.** It deletes the Exited job
  containers (backups stop silently). Images-only pruning is fine.
- **Don't stop the Unraid array while a disk operation runs** (parity sync, clear, rebuild).
  Stopping also makes every NAS mount in containers go stale.
- After restarting anything that mounts the NAS, the watchdog fixes stale mounts within
  2 minutes; `sudo systemctl start nas-watchdog.service` does it now.
