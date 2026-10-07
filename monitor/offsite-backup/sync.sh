#!/bin/sh
# Copy the borg repos (written by monitor/borgmatic: home-server-volumes nightly
# at 02:00; private weekly on Sunday 00:00) to Google Drive, each mounted
# at /repos/<name> and synced to gdrive:backups/<name>.
# Files the sync would delete or overwrite go to _deleted/<date> instead, so a
# damaged local repo can't wipe out the good offsite copy; those are kept
# KEEP_DAYS days. Problems are collected and sent as one ntfy alert at the end,
# so one bad repo doesn't stop the others from uploading.
set -u

REPOS="home-server-volumes private"
DELETED=gdrive:backups/_deleted
KEEP_DAYS=30
TODAY=$(date +%F)
FAILED=""

fail() {
  echo "ERROR: $1"
  FAILED="${FAILED}${FAILED:+
}$1"
}

for name in $REPOS; do
  REPO=/repos/$name
  DEST=gdrive:backups/$name
  if [ ! -f "$REPO/config" ]; then
    fail "Borg repo not found at $REPO (NAS share not mounted?)"
    continue
  fi
  # borg holds lock.exclusive / lock.roster while it writes; don't upload a half-written repo.
  if [ -e "$REPO/lock.exclusive" ] || [ -e "$REPO/lock.roster" ]; then
    fail "Borg repo $name is locked (borgmatic still running or crashed), skipped tonight's upload"
    continue
  fi
  rclone sync "$REPO" "$DEST" --backup-dir "$DELETED/$TODAY/$name" \
    --transfers 4 --stats-one-line --stats 0 -v \
    || fail "rclone sync to $DEST failed (see docker logs ofelia)"
done

# Drop _deleted/<date> folders older than KEEP_DAYS (names sort as dates).
# mkdir first so listing a never-used _deleted isn't an error. No pipeline into
# the loop: fail() must run in this shell, not a subshell.
cutoff=$(date -d "@$(( $(date +%s) - KEEP_DAYS * 86400 ))" +%F)
if rclone mkdir "$DELETED" && dirs=$(rclone lsf --dirs-only "$DELETED"); then
  for d in $(printf '%s\n' "$dirs" | tr -d /); do
    if [ "$d" \< "$cutoff" ]; then
      echo "pruning $DELETED/$d"
      rclone purge "$DELETED/$d" || fail "Could not prune $DELETED/$d"
    fi
  done
else
  fail "Could not list $DELETED to prune old copies"
fi

if [ -n "$FAILED" ]; then
  wget -q -O /dev/null --header "Authorization: Bearer $NTFY_TOKEN" \
    --header "Title: Offsite backup failed" --header "Priority: 4" --header "Tags: floppy_disk" \
    --post-data "$FAILED" "$NTFY_URL" || echo "ntfy publish failed too"
  exit 1
fi
echo "offsite backup OK ($TODAY)"
