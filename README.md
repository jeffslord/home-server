# home-server

Docker Compose stacks for my home server (`eris`, Ubuntu with a GTX 1080) and the Unraid NAS it mounts. Each folder is one stack; they share a Docker network, one reverse proxy and one login.

## How it fits together

- **One network.** Stacks join the external `web` bridge network and reach each other by container name (`http://grafana:3000`). Create it once with `docker network create web`.
- **One front door.** Caddy (`network/caddy`) terminates TLS for `*.$DOMAIN_NAME` using Cloudflare DNS challenges. Almost nothing publishes host ports; services are reached as `<name>.$DOMAIN_NAME`.
- **One login.** Caddy `forward_auth`s most sites to Authentik (`auth/`). Apps that support it (Grafana, Paperless, Actual, Open WebUI) also use Authentik OIDC, so there is no second login. fail2ban (`network/fail2ban`) watches Caddy's access log and bans in `DOCKER-USER`.
- **One scheduler.** Ofelia (`monitor/ofelia/config.ini`) holds every scheduled job: backups, the Actual sync and exports, and flight-site jobs. There is no host crontab. Run-to-completion services show as `Exited` between runs; that's intended.
- **DNS.** AdGuard Home (`network/adguard-home`) serves the LAN and split DNS for `$DOMAIN_NAME`. It is deliberately not on `web`: containers use the host IP for DNS, which a container on the same bridge can't reach (hairpin NAT).

## Stacks

| Folder | What runs | Notes |
|---|---|---|
| `auth/` | Authentik server, worker, Postgres | SSO for everything else |
| `network/caddy` | Caddy (custom build with the Cloudflare DNS module) | All routes in `config/Caddyfile`; reload with `caddy reload` |
| `network/adguard-home` | AdGuard Home | LAN DNS + ad blocking |
| `network/ddns-updater` | cloudflare-ddns | Keeps the public A record current |
| `network/fail2ban` | fail2ban (host network) | Jails for Caddy auth, bot scans, Home Assistant, Jellyfin |
| `household/home-assistant` | Home Assistant, Matter server, Z-Wave JS UI, ring-mqtt, Mosquitto, Whisper (GPU), Piper | Local voice for Assist via Wyoming |
| `household/paperless` | Paperless-ngx, Postgres, Redis | Authentik OIDC; AI suggestions on the local Ollama |
| `household/dawarich` | Dawarich, PostGIS, Redis, Photon | Self-hosted location history with local reverse geocoding |
| `household/mealie`, `household/grocy` | Mealie, Grocy | Recipes, pantry |
| `finance/actual-budget` | Actual Budget | Budget; OpenID via Authentik |
| `finance/helpers` | actual-helpers jobs, net-worth export, Money Ladder | SimpleFIN investment sync; SQLite export for Grafana's Net worth dashboard; `/money-ladder` page (r/personalfinance flowchart fed from Actual) |
| `health/garmin` | garmin-fetch-data, InfluxDB 1.11 | Garmin Connect → Grafana |
| `media/` | Jellyfin, Sonarr, Radarr, Prowlarr, Bazarr, Seerr, SABnzbd + qBittorrent (VPN), FlareSolverr | Library lives on the NAS |
| `games/launcher` | Start page + idle watcher, Docker socket proxy | Players start stopped servers; stops them after 30 idle minutes |
| `games/*` | Minecraft modpacks, Palworld, Space Engineers, Vintage Story | Each stack is its own server |
| `monitor/` | Prometheus, Alertmanager, Grafana, Loki, Alloy, node-exporter, cAdvisor, GPU exporter, blackbox, ntfy | Dashboards provisioned from `grafana/dashboards`; alerts to ntfy |
| `monitor/borgmatic` | borgmatic | Nightly borg backup of volumes to the NAS (02:00); weekly private repo |
| `monitor/offsite-backup` | rclone | Copies the borg repos to Google Drive (03:30) |
| `monitor/nas-watchdog` | systemd units + script | Waits for NAS mounts at boot; remounts and restarts dependent containers |
| `monitor/audit` | systemd user timer + script | Weekly read-only server snapshot, summarized by headless Claude and sent to ntfy |
| `monitor/ofelia`, `monitor/dockhand` | Ofelia, Dockhand | Scheduler; container management UI |
| `dev/opencode` | OpenCode web | AI coding agent behind Authentik |

## Configuration and secrets

Nothing secret is committed.

- **`.env`** at the repo root holds shared settings (`SSD_PATH`, `HDD_PATH`, `DOMAIN_NAME`, `PUID`/`PGID`, `TZ`, passwords). Each stack folder has a `.env` symlink to it (`ln -s ../.env .env`). A few stacks with their own credentials (`finance/helpers`, `monitor/borgmatic`, `monitor/offsite-backup`) keep a separate `.env`. Start from `env_template.env`.
- **`_secrets/`** holds files mounted as Compose secrets (OIDC client secrets, API tokens). Containers that run as a non-root user need the file to be readable by that user.
- **`private/`** holds stacks and backup definitions that stay out of the public repo.
- **Data** lives under `$SSD_PATH/<service>` (fast, backed up nightly) or `$HDD_PATH` (bulk media), never in the repo.

All four (`.env`, `_secrets/`, `private/`, `_storage/`) are gitignored.

## Running a stack

```sh
cd household/paperless
docker compose up -d          # start or apply changes
docker compose logs -f        # follow logs
```

After editing `network/caddy/config/Caddyfile`:

```sh
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Scheduled jobs are edited in `monitor/ofelia/config.ini`; restart the `ofelia` container to pick them up. Their output is in `docker logs ofelia`.
