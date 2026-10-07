#!/usr/bin/env bash
# Keep the NFS shares from the NAS (every nfs line in /etc/fstab) mounted and the
# containers that bind them running. Runs as root from systemd (see ./systemd/):
#   nas-watchdog.sh wait   at boot, before docker: wait up to WAIT_SECS for the shares
#   nas-watchdog.sh        every 2 min: remount failed/stale shares, then start
#                          containers that failed on a missing share and restart
#                          ones whose share was remounted under them
# The NAS being down is not an error: it logs and waits for the next run.
set -uo pipefail

WAIT_SECS=300
REPO=/home/jeff/development/github.com/home-server
NTFY_URL=https://ntfy.jeffslord.com/unraid
NTFY_TOKEN=$(grep -m1 '^NTFY_TOKEN=' "$REPO/monitor/offsite-backup/.env" 2>/dev/null | cut -d= -f2-)

mapfile -t SHARES < <(awk '!/^#/ && $3 ~ /^nfs/ {print $2}' /etc/fstab)
NAS=$(awk '!/^#/ && $3 ~ /^nfs/ {split($1, a, ":"); print a[1]; exit}' /etc/fstab)

notify() {  # notify <title> <body>
  curl -s -m 15 -o /dev/null -H "Authorization: Bearer $NTFY_TOKEN" -H "Title: $1" \
    -H "Priority: 3" -H "Tags: floppy_disk" --data-binary "$2" "$NTFY_URL" || true
}

nas_up() {  # NFS port open and the NAS is exporting at least one share
  timeout 5 bash -c "</dev/tcp/$NAS/2049" 2>/dev/null &&
    timeout 10 showmount -e "$NAS" 2>/dev/null | grep -q '^/'
}

unit() { systemd-escape --path "$1"; }

# Readable and actually NFS (not the empty local dir under it). Touching it
# triggers the automount. SIGKILL because a hard mount to a dead server ignores TERM.
share_ok() {
  timeout -s KILL 15 stat -t "$1/." >/dev/null 2>&1 &&
    findmnt -n -o FSTYPE --target "$1" 2>/dev/null | tail -1 | grep -q '^nfs'
}

remount() {  # drop a stale/failed mount and re-arm its automount
  local u; u=$(unit "$1")
  umount -l "$1" 2>/dev/null
  systemctl reset-failed "$u.mount" "$u.automount" 2>/dev/null
  systemctl restart "$u.automount"
  share_ok "$1"
}

if [ "${1:-}" = wait ]; then
  deadline=$((SECONDS + WAIT_SECS))
  while :; do
    pending=()
    if nas_up; then
      for s in "${SHARES[@]}"; do share_ok "$s" || remount "$s" || pending+=("$s"); done
      [ ${#pending[@]} -eq 0 ] && { echo "all NAS shares mounted"; exit 0; }
    fi
    if [ $SECONDS -ge $deadline ]; then
      echo "gave up after ${WAIT_SECS}s (NAS $NAS up: $(nas_up && echo yes || echo no); pending: ${pending[*]:-all})"
      exit 0   # never block docker for good; the timer picks it up from here
    fi
    sleep 10
  done
fi

nas_up || { echo "NAS $NAS not reachable, nothing to do"; exit 0; }

remounted=() broken=()
for s in "${SHARES[@]}"; do
  share_ok "$s" && continue
  echo "$s not usable, remounting"
  if remount "$s"; then remounted+=("$s"); else echo "$s still not mountable"; broken+=("$s"); fi
done

uses() {  # uses <container> <share...>: true if it binds a path under any given share
  local src c=$1; shift
  for src in $(docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}} {{end}}{{end}}' "$c"); do
    for s in "$@"; do [[ $src == "$s" || $src == "$s"/* ]] && return 0; done
  done
  return 1
}

fixed=()
for c in $(docker ps -aq); do
  read -r name policy status err < <(docker inspect -f \
    '{{slice .Name 1}} {{.HostConfig.RestartPolicy.Name}} {{.State.Status}} {{.State.Error}}' "$c")
  [[ $policy == unless-stopped || $policy == always ]] || continue   # skip one-shot jobs
  uses "$c" "${SHARES[@]}" || continue
  if [ ${#broken[@]} -gt 0 ] && uses "$c" "${broken[@]}"; then
    echo "leaving $name alone until its share mounts"; continue
  fi
  if [ "$status" = running ]; then
    if [ ${#remounted[@]} -gt 0 ] && uses "$c" "${remounted[@]}"; then
      echo "restarting $name (share remounted under it)"
      docker restart "$c" >/dev/null && fixed+=("$name")
    fi
  elif [ "$status" = exited ] && [ -n "$err" ]; then   # failed to start, not a manual stop
    echo "starting $name (last start failed: $err)"
    docker start "$c" >/dev/null && fixed+=("$name")
  fi
done

if [ ${#remounted[@]} -gt 0 ] || [ ${#fixed[@]} -gt 0 ]; then
  notify "NAS watchdog recovered" "Remounted: ${remounted[*]:-none}. Containers: ${fixed[*]:-none}."
fi
