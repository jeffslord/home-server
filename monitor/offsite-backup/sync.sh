#!/bin/sh
# Copy the borg repo (written by monitor/borgmatic at 02:00) to Google Drive.
# Files the sync would delete or overwrite go to _deleted/<date> instead, so a
# damaged local repo can't wipe out the good offsite copy; those are kept
# KEEP_DAYS days. Any failure publishes an ntfy alert.
set -u

REPO=/repo
DEST=gdrive:backups/home-server-volumes
DELETED=gdrive:backups/_deleted
KEEP_DAYS=30
TODAY=$(date +%F)

alert() {
  echo "ERROR: $1"
  wget -q -O /dev/null --header "Authorization: Bearer $NTFY_TOKEN" \
    --header "Title: Offsite backup failed" --header "Priority: 4" --header "Tags: floppy_disk" \
    --post-data "$1" "$NTFY_URL" || echo "ntfy publish failed too"
  exit 1
}

[ -f "$REPO/config" ] || alert "Borg repo not found at $REPO (NAS share not mounted?)"
# borg holds lock.exclusive / lock.roster while it writes; don't upload a half-written repo.
if [ -e "$REPO/lock.exclusive" ] || [ -e "$REPO/lock.roster" ]; then
  alert "Borg repo is locked (borgmatic still running or crashed), skipped tonight's upload"
fi

rclone sync "$REPO" "$DEST" --backup-dir "$DELETED/$TODAY" \
  --transfers 4 --stats-one-line --stats 0 -v \
  || alert "rclone sync to $DEST failed (see docker logs ofelia)"

# Drop _deleted/<date> folders older than KEEP_DAYS (names sort as dates).
cutoff=$(date -d "@$(( $(date +%s) - KEEP_DAYS * 86400 ))" +%F)
rclone lsf --dirs-only "$DELETED" 2>/dev/null | tr -d / | while read -r d; do
  if [ "$d" \< "$cutoff" ]; then
    echo "pruning $DELETED/$d"
    rclone purge "$DELETED/$d" || alert "Could not prune $DELETED/$d"
  fi
done

echo "offsite backup OK ($TODAY)"
