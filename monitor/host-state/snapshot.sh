#!/usr/bin/env bash
# What a rebuild of eris needs to know that isn't a file in /etc (which borgmatic backs up
# as /host/etc): installed packages, enabled units, versions. Writes plain text files to
# $OUT, which borgmatic backs up nightly. Read-only otherwise; runs as jeff (no sudo) from
# monitor/audit/weekly-audit.sh. Used by docs/runbooks/disaster-recovery.md.
set -uo pipefail

OUT=${1:-/home/jeff/volumes/monitor/host-state}
mkdir -p "$OUT"
cd "$OUT" || exit 1

apt-mark showmanual | sort > apt-manual.txt              # reinstall: xargs -a apt-manual.txt sudo apt install -y
dpkg --get-selections > dpkg-selections.txt
snap list 2>/dev/null > snap-list.txt
systemctl list-unit-files --state=enabled --no-legend > systemd-enabled.txt
systemctl --user list-unit-files --state=enabled --no-legend > systemd-user-enabled.txt
crontab -l > crontab-jeff.txt 2>&1
{
  echo "snapshot: $(date -Is)"
  . /etc/os-release && echo "os: $PRETTY_NAME"
  echo "kernel: $(uname -r)"
  echo "docker: $(docker version --format '{{.Server.Version}}' 2>&1)"
  echo "compose: $(docker compose version --short 2>&1)"
  echo "nvidia: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1)"
  echo "nvidia packages: $(dpkg -l 'nvidia-*' 'libnvidia-*' 2>/dev/null | awk '/^ii/ && /nvidia-(driver|dkms|container-toolkit)/ {print $2"="$3}' | tr '\n' ' ')"
  echo "docker networks: $(docker network ls --format '{{.Name}}' | grep -vE '^(bridge|host|none)$' | sort | tr '\n' ' ')"
} > versions.txt
echo "host-state written to $OUT"
