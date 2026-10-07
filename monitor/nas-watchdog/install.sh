#!/bin/sh
# Install the NAS watchdog (run with sudo). Safe to re-run after editing.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
install -m 755 "$HERE/nas-watchdog.sh" /usr/local/sbin/nas-watchdog
install -m 644 "$HERE/systemd/nas-wait.service" "$HERE/systemd/nas-watchdog.service" \
  "$HERE/systemd/nas-watchdog.timer" /etc/systemd/system/
install -d /etc/systemd/system/docker.service.d
install -m 644 "$HERE/systemd/docker-wait-for-nas.conf" /etc/systemd/system/docker.service.d/wait-for-nas.conf
systemctl daemon-reload
systemctl enable --now nas-watchdog.timer
