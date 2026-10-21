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
6. Images: compose files pin versions, so `docker compose up -d` pulls what you ran before.
   For anything still on `latest`, take the digest from the restored
   `volumes/monitor/docker-state/running-images.tsv` if a newer image misbehaves.
   `docker network create web`, then bring stacks up in order: `network/caddy`, `network/adguard-home`,
   `auth`, `monitor`, then everything else (`docker compose up -d` in each).
7. Host config. The old `/etc` is in the archive at `/srv/r/host/etc`, and package/unit lists are in
   `/home/jeff/volumes/monitor/host-state/` (`versions.txt` has the old kernel, Docker and NVIDIA versions).
   **Copy files selectively, never the whole `/etc`** (disk UUIDs, netplan and machine IDs differ):
   ```sh
   E=/srv/r/host/etc; H=/home/jeff/volumes/monitor/host-state
   xargs -a $H/apt-manual.txt sudo apt install -y     # same packages (ignore any that no longer exist)
   sudo cp $E/docker/daemon.json /etc/docker/ && sudo systemctl restart docker
   sudo cp $E/cron.daily/docker-prune-daily /etc/cron.daily/    # image-only prune, NOT system prune
   sudo cp -a $E/ufw/user.rules $E/ufw/user6.rules /etc/ufw/ && sudo ufw enable
   sudo cp -a $E/ssh/ssh_host_* /etc/ssh/ && sudo systemctl restart ssh   # clients won't see a new host key
   diff <(grep nfs $E/fstab) <(grep nfs /etc/fstab)    # NAS lines should match step 3
   sudo ~/development/github.com/home-server/monitor/nas-watchdog/install.sh   # boot wait + watchdog
   ```
   Then re-enable the user units listed in `$H/systemd-user-enabled.txt` (weekly audit:
   `monitor/audit/systemd`; `claude remote-control`, if wanted) and compare `$H/systemd-enabled.txt`
   with `systemctl list-unit-files --state=enabled` for anything else that was turned on.
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
