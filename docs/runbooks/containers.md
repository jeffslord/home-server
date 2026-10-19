# Containers

Alerts: `ContainerNotRunning`, `ContainerUnhealthy`, `ContainerRestarting`, `ContainerOomKilled`,
`ContainerNearMemoryLimit`, `InfraContainerGone`, `FlightSite*`.

## Check

```sh
docker ps -a --filter name=<name> --format '{{.Names}}\t{{.Status}}'
docker logs --tail 50 <name>
docker inspect -f '{{json .State}}' <name> | python3 -m json.tool   # exit code, OOMKilled, health log
```

Find the stack that owns it:

```sh
docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' <name>
```

## Fix

| What you see | Do this |
|---|---|
| Exited, logs show nothing odd | `docker start <name>` |
| Config changed or container gone | `cd <stack dir> && docker compose up -d` |
| Logs: `Stale file handle`, `ESTALE`, `-116`, `EACCES` on `/data`, or a library suddenly empty | NAS mount went stale: `sudo systemctl start nas-watchdog.service`, or just `docker restart <name>`. See [nas.md](nas.md). |
| Restart loop after an image update | Pin the previous tag in the compose file, `docker compose up -d`. Old tags: `docker image ls <image>` |
| OOM-killed / near limit | Raise `mem_limit` in the compose file or find the leak in `docker stats --no-stream` |
| Unhealthy but working | `docker inspect -f '{{json .State.Health.Log}}' <name>` shows the failing probe |

### `InfraContainerGone` (critical)

caddy, adguardhome, authentik or home-assistant is missing. With Caddy or Authentik down,
**every** website is down; with AdGuard down, LAN DNS is down.

```sh
docker ps -a | grep -E 'caddy|adguardhome|authentik|home-assistant'
cd ~/development/github.com/home-server/network/caddy && docker compose up -d
cd ~/development/github.com/home-server/network/adguard-home && docker compose up -d
cd ~/development/github.com/home-server/auth && docker compose up -d
cd ~/development/github.com/home-server/household/home-assistant && docker compose up -d
```

If AdGuard won't start, the family's internet "breaks" (DNS). Quick bypass: in the router,
set DNS to `1.1.1.1` until it's fixed.

If cAdvisor was restarted or the host rebooted and the alert fires but everything is up,
that's the cAdvisor boot race: `docker restart cadvisor`.

### Expected-to-be-stopped containers

These are Exited by design and are ignored by the alerts and `bin/health`:
Ofelia jobs (`borgmatic`, `borgmatic-private`, `offsite-backup`, `actual-helpers`,
`actual-networth`, `flightdensity-report`) and on-demand game servers (started from the
games launcher, stopped after 30 idle minutes). A failed job raises `ScheduledJobFailed`
instead → [backups.md](backups.md).

## Updating a container safely

```sh
cd <stack dir>
docker compose pull && docker compose up -d
docker logs -f <name>          # watch it come up
```

If the stack has a database, check that last night's backup succeeded first (`bin/health`).
Before a major version jump (Immich, Authentik, Paperless, Postgres), take a one-off dump:
`docker start -a borgmatic` runs a full backup now.
