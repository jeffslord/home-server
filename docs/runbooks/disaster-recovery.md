# Disaster recovery

## Keep these OUTSIDE the server (check yearly)

Without these, the backups can't be used. Store them in a password manager:

- [ ] **Borg passphrase** (home-server repo) and the private repo's passphrase
- [ ] **Unraid flash backup zip**, which includes the disk encryption keyfile ([nas.md](nas.md#encryption-key-read-this-before-you-ever-need-it))
- [ ] Unraid root password
- [ ] Google account login (Drive holds the offsite copy)
- [ ] GitHub login (this repo: `jeffslord/home-server`)
- [ ] Cloudflare login (DNS for `jeffslord.com`)
- [ ] healthchecks.io login

## Scenario: eris's disk or OS is dead, NAS is fine

Recovery time is a few hours. Data loss is at most since the last 02:00 backup.

1. **Household first:** set the router's DNS to `1.1.1.1` (AdGuard lived on eris).
2. Install Ubuntu Server 24.04 and create user `jeff` (uid 1000). Install Docker Engine + the compose
   plugin, NVIDIA driver + `nvidia-container-toolkit`, `nfs-common`.
3. NAS mounts: `sudo mkdir -p /mnt/nas/{media,stash,backup,photos}`, then add one line per share
   to `/etc/fstab`:
   ```
   192.168.1.172:/mnt/user/media /mnt/nas/media nfs4 rw,hard,noauto,_netdev,x-systemd.automount,nofail,timeo=600,retrans=2 0 0
   ```
   (same for `stash`, `backup` and `photos`). Check that `sudo systemctl daemon-reload && ls /mnt/nas/backup` works.
4. Restore everything from borg with plain `borg` (borgmatic's config is itself inside the backup):
   ```sh
   sudo mkdir -p /srv/r
   read -rs -p 'borg passphrase: ' BORG_PASSPHRASE; export BORG_PASSPHRASE; echo
   docker run --rm -e BORG_PASSPHRASE --entrypoint sh \
     -v /mnt/nas/backup/home-server-volumes:/repo:ro -v /srv/r:/r \
     ghcr.io/borgmatic-collective/borgmatic:2.1.8 \
     -c 'cd /r && borg extract --bypass-lock --progress "/repo::$(borg list --bypass-lock --short --last 1 /repo)"'
   ```
   (tested read-only against the live repo on 2026-10-19). That one extract restores `home/jeff/volumes`, the
   `home-server` repo **with** `.env` and `_secrets/`, `.ssh`, `.config` (rclone), `flightdensity`, etc.
   Copy it into place: `sudo cp -a /srv/r/home/jeff/. /home/jeff/`. Borg kept the original owners,
   and `-a` preserves them. Paperless documents come back under `/srv/r/mnt/nas/paperless/media`.
5. Restore the databases: start each DB container alone (`docker compose up -d <db service>`), then
   the per-database `restore` from [backups.md](backups.md). Postgres data dirs were excluded
   on purpose; only the dumps are in the archive.
6. `docker network create web`, then bring stacks up in order: `network/caddy`, `network/adguard-home`,
   `auth`, `monitor`, then everything else (`docker compose up -d` in each).
7. Host bits that aren't Docker:
   - `monitor/nas-watchdog/install.sh` (boot wait + watchdog)
   - `monitor/audit/systemd` (weekly audit, user units)
   - the image-only prune in `/etc/cron.daily/docker-prune-daily` (**not** `system prune`)
   - `/etc/docker/daemon.json`: `dns` → `192.168.1.162`, `1.1.1.1`; log-opts `max-size 20m`/`max-file 3`; `live-restore`; nvidia runtime
   - the systemd user unit for `claude remote-control`, if wanted
8. Put the router's DNS back to AdGuard (192.168.1.162). Run `bin/health`.

## Scenario: NAS dead (hardware), disks fine

Unraid stores the config on the flash drive and the data on the disks. Move the disks and the
flash drive to any machine that boots from USB. Disk order doesn't matter (Unraid matches by
serial). Start the array. The keyfile on the flash unlocks the disks.

## Scenario: NAS flash drive dead

Restore from the flash backup zip ([nas.md](nas.md#encryption-key-read-this-before-you-ever-need-it)).
**Without a backup of `config/keyfile` the encrypted disks can't be unlocked.**

## Scenario: NAS array lost (e.g. 2+ disks failed)

- eris app data: intact on eris; the borg repo is also on Drive → restore the repo from Drive
  ([backups.md](backups.md#from-google-drive-the-nas-is-gone)).
- Paperless documents: in borg → restore.
- Media: re-acquire via Sonarr/Radarr (their DBs are in borg).
- **Photos (Immich originals) have no copy outside the NAS.** That data is gone.

## Scenario: house gone (fire, theft)

Only Google Drive survives: the borg repos (app data, configs, databases, Paperless documents).
Follow "eris dead" on new hardware, using the Drive restore. Media and Immich photos are lost
unless they also live elsewhere (e.g. phones / Google Photos).
