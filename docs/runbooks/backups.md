# Backups and restores

Alerts: `ScheduledJobFailed`, `ScheduledJobMissing`, "Home server backup failed" (ntfy `unraid`),
the NAS freshness alert (borg repo not written for 30 h), "offsite backup failed".

## What is backed up, where

| Data | How | Where |
|---|---|---|
| `~/volumes` (app data), this repo incl. `.env` + `_secrets/`, `~/flightdensity`, `~/.ssh`, `~/.config`, `~/.claude`, misc home projects | borgmatic, nightly 02:00 | borg repo `/mnt/nas/backup/home-server-volumes` |
| Postgres: authentik, paperless, dawarich, sure, both Immich DBs | `pg_dump` inside the same archive | same |
| SQLite: Home Assistant, zigbee, Grafana, Actual, *arr, Jellyfin, flights, stash | consistent dump inside the same archive | same |
| Paperless documents | borgmatic (from the NAS) | same |
| Unraid flash config + disk keyfile | NAS cron 01:30 → `backup/unraid-flash`, then borgmatic | same |
| The borg repos | rclone, nightly 03:30 | Google Drive `backups/` (deleted/changed files kept 30 days under `_deleted/`) |
| Media, photos on the NAS | Unraid parity only | **No offsite copy** |

Retention: 7 daily, 4 weekly, 6 monthly. Repo and archive checks run weekly.
The borg repo is encrypted (repokey); you need the **borg passphrase** to read it,
from your password manager. The key itself is inside the repo.

## A backup failed

```sh
bin/health                                      # which job, exit code, when
docker logs --tail 40 borgmatic                 # or offsite-backup / borgmatic-private
docker logs --since 24h ofelia 2>&1 | grep -i fail
```

| Error | Fix |
|---|---|
| `Cannot find variable X in environment` | `.env` was edited but the container wasn't recreated: `cd monitor/borgmatic && docker compose create --force-recreate` |
| Can't reach a database host | That DB container is down, or the compose `networks:` is missing its network → recreate as above |
| `Failed to create/acquire the lock` | A previous run died. Check nothing is running (`docker ps \| grep borg`), then `docker compose run --rm borgmatic borg break-lock` |
| NAS path missing | [nas.md](nas.md) |
| offsite: `rclone.conf: permission denied` | Something ran rclone as root: `docker run --rm -v ~/.config/rclone:/c alpine:3 chown 1000:1000 /c/rclone.conf` |
| offsite: `invalid_grant` / `unauthorized_client` | The Google token expired: `docker run --rm -it --user 1000:1000 -v ~/.config/rclone:/config/rclone rclone/rclone:1.75 config reconnect gdrive:` |
| `No such container` | Pruned. Recreate without running: `docker compose create` in `monitor/borgmatic`, `monitor/offsite-backup`, `private/backup`, `finance/helpers`, `~/flightdensity` |

Re-run now (both take a few minutes):

```sh
docker start -a borgmatic && docker start -a offsite-backup
```

Any ad-hoc rclone container that mounts `~/.config/rclone` **must** use `--user 1000:1000`.

## Restoring

All commands run from `monitor/borgmatic`. Restored files come out owned by root.

```sh
cd ~/development/github.com/home-server/monitor/borgmatic
docker compose run --rm borgmatic repo-list                       # archives (eris-YYYY-MM-DD…)
docker compose run --rm borgmatic list --archive latest --find '*paperless*' | head
```

### A file or folder (to a scratch dir, then copy back)

```sh
mkdir -p /tmp/restore
docker compose run --rm -v /tmp/restore:/restore borgmatic extract \
  --archive latest --path home/jeff/volumes/<path> --destination /restore
sudo ls -la /tmp/restore/home/jeff/volumes/<path>
```

Paths have no leading `/`. Use a specific archive name instead of `latest` to go back in time.
To replace an app's data: stop the app, move its folder aside, copy the restored one in, start it.

### A database (overwrites the live database)

1. Stop the app but **leave its DB container running**, e.g. `docker stop authentik-server authentik-worker`.
2. Restore:
   ```sh
   docker compose run --rm borgmatic restore --archive latest --database authentik
   ```
   Names: `authentik`, `paperless`, `dawarich`, `sure_production`, `immich` (two of them, so add
   `--original-label immich-photos` or `--original-label immich`), and the SQLite names:
   `home-assistant`, `zigbee`, `grafana`, `actual-*`, `sonarr`, `radarr`, `jellyfin`, `flights`, `stash`.
   For SQLite, stop the app container first (the file is replaced in place).
3. Start the app, check it.

To inspect a dump without touching anything: extract `borgmatic/postgresql_databases/<host>/<db>` with
the extract command above, then
`docker run --rm -v /tmp/restore:/r postgres:18-alpine pg_restore --list /r/borgmatic/postgresql_databases/<host>/<db>`.
Use pg_restore **18**: older versions can't read these dumps (pg_dump 18).

### From Google Drive (the NAS is gone)

```sh
mkdir -p /srv/restore-repo
docker run --rm --user 1000:1000 -v ~/.config/rclone:/config/rclone -v /srv/restore-repo:/data \
  rclone/rclone:1.75 copy gdrive:backups/home-server-volumes /data/home-server-volumes
```

Then point the `repositories:` path in `config.yaml` (and the compose bind) at
`/srv/restore-repo/home-server-volumes` and restore as above. If `~/.config/rclone` is gone too,
see [disaster-recovery.md](disaster-recovery.md).

## Restore drill (do quarterly)

The last drill was on 2026-10-19: a file extract plus an authentik dump verified with `pg_restore --list` (385 tables).

```sh
cd ~/development/github.com/home-server/monitor/borgmatic && mkdir -p /tmp/restore
docker compose run --rm -v /tmp/restore:/restore borgmatic extract --archive latest \
  --path borgmatic/postgresql_databases/authentik-postgresql/authentik --destination /restore
docker run --rm -v /tmp/restore:/r postgres:18-alpine pg_restore --list \
  /r/borgmatic/postgresql_databases/authentik-postgresql/authentik | grep -c 'TABLE DATA'   # > 300
docker run --rm -v /tmp:/t alpine:3 rm -rf /t/restore
```

Update the date above when you do it.
