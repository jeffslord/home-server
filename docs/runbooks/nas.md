# NAS (Unraid, 192.168.1.172)

Alerts: `NasShareNotMounted`, `NasShareAlmostFull`, `HostUnreachable` (192.168.1.172), and
everything on the ntfy topic `unraid` (SMART, temperatures, array errors, parity).

## Access

| How | When |
|---|---|
| https://nas.jeffslord.com | Normal (Caddy + Authentik, then Unraid login) |
| http://192.168.1.172 | eris/Caddy/Authentik down; LAN only |
| Tailscale (the NAS runs the plugin) | Away from home with eris down |
| `ssh unraid` from eris | Shell. The key has a passphrase; load it once per session (below) |

```sh
# load the NAS key for 12 h (asks for the passphrase)
rm -f ~/.ssh/agent-unraid.sock; ssh-agent -a ~/.ssh/agent-unraid.sock -t 12h >/dev/null \
  && SSH_AUTH_SOCK=~/.ssh/agent-unraid.sock ssh-add ~/.ssh/id_ed25519_unraid
ssh -o IdentityAgent=~/.ssh/agent-unraid.sock unraid
```

`bin/health` uses the same socket to show the array state.

## Shares missing or stale on eris

The shares (`/mnt/nas/{media,stash,backup,photos}`) are NFS automounts. `nas-watchdog`
(systemd timer, every 2 min) remounts dead shares and restarts containers whose view of a
share went stale. It posts "NAS watchdog recovered" to `unraid` when it does.

```sh
sudo systemctl start nas-watchdog.service && journalctl -u nas-watchdog.service -n 20
```

Still broken:

| Cause | Do |
|---|---|
| NAS down / array stopped | Fix the NAS first (GUI → Main → Start). The watchdog catches up within 2 min. |
| One container still shows errors | `docker restart <name>` (stale handles can appear only on later access) |
| Mount hangs | `sudo umount -l /mnt/nas/<share>` then rerun the watchdog |

After **any** NAS array stop/start or reboot, expect stale handles in Immich, Jellyfin,
the *arr apps, stash and the download clients. The watchdog handles it; verify with `bin/health`.

## Disk alerts (ntfy `unraid`)

1. Open GUI → Main. Note which disk, its status, and its error count.
2. GUI → click the disk → SMART attributes. What matters: 5 (reallocated),
   187 (reported uncorrectable), 197 (pending), 198 (offline uncorrectable), 199 (CRC).
3. Decide:

| Situation | Do |
|---|---|
| Temperature warning only | Check airflow; drives run 45–54 °C under load. Nothing to fix if it settles. |
| CRC count (199) rising, others 0 | Cable. Reseat or replace the SATA cable during a planned shutdown. |
| Pending/uncorrectable rising | The drive is failing. Plan the replacement now; don't start big writes. |
| Disk **disabled** (red X), parity healthy | Unraid emulates it from parity. Replace the drive; Unraid rebuilds onto the new one. |
| Parity disabled | Array runs unprotected. Replace the parity drive; Unraid rebuilds parity. |
| Two failures with single parity | Data on the failed data disk is lost from the array. Restore what's needed from backups. |

### Replacing a drive

1. Wait for any running operation to finish (Main shows sync/clear/rebuild progress).
2. GUI → Main → **Stop** array. (Everything that mounts the NAS goes stale; the watchdog fixes it afterwards.)
3. Power down if there are no hot-swap bays, swap the drive, power up.
4. Main → assign the new drive to the empty slot → Start. Unraid rebuilds data or parity.
   **Before formatting a brand-new data disk, set its file system to `xfs - encrypted`.**
   The default is unencrypted, and every other disk is encrypted.
5. Don't stop the array until the rebuild finishes. Watch progress in Main or with `bin/health`.

## Encryption key (read this before you ever need it)

Every data disk and the cache are LUKS-encrypted. The unlock key is `/boot/config/keyfile`
on the **USB flash drive**; `/boot/config/go` copies it into place at boot.
**If the flash drive dies and there's no copy of that keyfile, all array data is unreadable.**

Automatic: a NAS cron (`/boot/config/plugins/dynamix/flash-backup.cron`, 01:30) runs
`/boot/config/custom/flash-backup.sh`, which writes `config/` to `/mnt/user/backup/unraid-flash/`
(14 days, mode 600, owner nobody). borgmatic includes that folder at 02:00 and rclone copies it to
Google Drive at 03:30. `bin/health` warns if the newest copy is older than 48 h. To recover the key
without the NAS: restore `mnt/nas/backup/unraid-flash` from borg ([backups.md](backups.md)), then
`tar -xzf flash-*.tgz config/keyfile`.

Also keep a manual copy off the NAS (it doesn't depend on the borg passphrase):

- GUI → Main → Boot Device → Flash → **Flash Backup**. This downloads a zip that includes the keyfile.
  Store it in your password manager or another place that isn't the NAS or eris. Redo it after any
  change to disks, shares or plugins.

Restoring a dead flash drive: write the Unraid USB creator image to a new stick, copy the
backup's `config/` folder onto it, boot, then transfer the license to the new GUID
(Tools → Registration).

## Capacity

The array is near full (about 2.4–3.3 TB free). `NasShareAlmostFull` fires below 5%.
Add a disk using "Replacing a drive" step 4, or prune media.

## Gotchas

- An array stop/start re-probes **all** drives, including unassigned ones mid-operation.
- `pkill -f <pattern>` over ssh kills your own ssh session if the pattern is in its command line; kill by pid.
- `/root` and `/tmp` on the NAS are RAM. Logs/scripts you want to keep go in `/boot/config/custom/`.
- Unraid notifications reach the phone only for warning/alert levels (`dynamix.cfg`: `warning="5"`, `alert="5"`).
