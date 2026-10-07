#!/usr/bin/env bash
# Weekly server audit, step 1: gather facts about eris with read-only commands.
# Prints a plain-text snapshot on stdout; weekly-audit.sh hands it to Claude.
# Nothing here changes state. Every section is best-effort: a failing command
# prints its error and the audit carries on.
set -uo pipefail

REPO=/home/jeff/development/github.com/home-server
PROM=http://127.0.0.1:9092          # Prometheus, host-only port (monitor stack)
# Containers that run on a schedule and are expected to be "Exited (0)".
ONE_SHOT='^(borgmatic|borgmatic-private|offsite-backup|actual-helpers|actual-networth|flightdensity-report)$'

section() { printf '\n## %s\n' "$1"; }
promq() {  # promq <promql> -> "label=value ... => value" lines
  curl -s -m 20 "$PROM/api/v1/query" --data-urlencode "query=$1" | python3 -c '
import json, sys
try:
    for r in json.load(sys.stdin)["data"]["result"]:
        m = r["metric"]; v = r["value"][1]
        print(" ".join(f"{k}={m[k]}" for k in sorted(m) if k != "__name__"), "=>", v)
except Exception as e:
    print("query failed:", e)'
}

echo "# eris snapshot $(date -Is)"

section "Host"
uptime
[ -f /var/run/reboot-required ] && echo "REBOOT REQUIRED since $(stat -c %y /var/run/reboot-required | cut -d. -f1)" || echo "no reboot required"
echo "upgradable packages: $(apt list --upgradable 2>/dev/null | grep -c upgradable)"
free -h | sed -n 1,3p
df -h --output=target,size,used,avail,pcent / /mnt/nas/media /mnt/nas/backup /mnt/nas/stash 2>&1
nvidia-smi --query-gpu=name,driver_version,temperature.gpu,memory.used,memory.total --format=csv,noheader 2>&1

section "Containers not running (excluding scheduled one-shot jobs)"
docker ps -a --format '{{.Names}}\t{{.Status}}' | grep -v $'\tUp ' | awk -F'\t' -v re="$ONE_SHOT" '$1 !~ re' | grep . || echo "none"

section "Unhealthy, restarting, or OOM-killed containers"
docker ps -aq | xargs docker inspect -f '{{.Name}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' \
  | sed 's#^/##' | awk '$2 ~ /unhealthy/ || $3 != "restarts=0" || $4 == "oom=true"' || true

section "Scheduled jobs (last result of each one-shot container)"
for c in borgmatic borgmatic-private offsite-backup actual-helpers actual-networth flightdensity-report; do
  docker inspect -f "$c exit={{.State.ExitCode}} finished={{.State.FinishedAt}}" "$c" 2>&1 | cut -c1-90
done
echo "ofelia job failures in the last 7 days:"
docker logs --since 168h ofelia 2>&1 | grep -E 'failed: true' | sed -E 's/.*\[Job "([^"]+)".*error: (.*)/  \1: \2/' | sort | uniq -c || true
echo "last borgmatic summary lines:"
docker logs --tail 5 borgmatic 2>&1 | sed 's/^/  /'
echo "last offsite-backup line: $(docker logs --tail 1 offsite-backup 2>&1)"

section "Prometheus: alerts firing now"
promq 'ALERTS{alertstate="firing"}'
section "Prometheus: alerts that fired during the last 7 days (samples firing)"
promq 'sum by (alertname) (count_over_time(ALERTS{alertstate="firing"}[7d]))'
section "Blackbox: endpoints under 99.5% availability over 7 days (fraction up)"
promq 'avg_over_time(probe_success[7d]) < 0.995'
section "TLS: days until earliest certificate expiry"
promq 'min by (instance) ((probe_ssl_earliest_cert_expiry - time()) / 86400) < 30'
section "Disk growth: filesystems predicted to fill within 14 days"
promq 'predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}[7d], 14*86400) < 0'

section "Container log error counts, last 7 days (top 12)"
for c in $(docker ps --format '{{.Names}}'); do
  n=$(docker logs --since 168h "$c" 2>&1 | grep -ciE '\b(error|exception|traceback|fatal)\b')
  [ "$n" -gt 0 ] && echo "$n $c"
done | sort -rn | head -12

section "fail2ban"
for j in $(docker exec fail2ban fail2ban-client status 2>/dev/null | sed -n 's/.*Jail list:\s*//p' | tr ',' ' '); do
  docker exec fail2ban fail2ban-client status "$j" 2>/dev/null | awk -v j="$j" '/Currently banned|Total banned/{gsub(/[|`-]/,""); printf "%s %s; ", j, $0} END{print ""}'
done

section "Images: running containers on images older than 90 days"
docker ps --format '{{.Names}} {{.Image}}' | while read -r name img; do
  created=$(docker image inspect -f '{{.Created}}' "$img" 2>/dev/null | cut -c1-10)
  [ -n "$created" ] && [ "$(( ( $(date +%s) - $(date -d "$created" +%s) ) / 86400 ))" -gt 90 ] && echo "$name $img built $created"
done
docker system df 2>&1

section "Compose drift (running config differs from the compose file on disk)"
# Compose's own dry run is the oracle; comparing `config --hash` to the container
# label gives false positives (secrets/env_file services).
docker ps --format '{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.project.working_dir"}}|{{.Label "com.docker.compose.service"}}' \
  | sort -u | awk -F'|' '$1 != "" {svcs[$1"|"$2] = svcs[$1"|"$2] " " $3} END {for (k in svcs) print k "|" svcs[k]}' \
  | while IFS='|' read -r proj dir svcs; do
    [ -d "$dir" ] || { echo "$proj: compose dir $dir no longer exists"; continue; }
    # shellcheck disable=SC2086
    (cd "$dir" && docker compose -p "$proj" up -d --no-deps --pull never --dry-run $svcs 2>&1) \
      | grep -E ' Recreate *$' | sed -E "s/^ *Container (.*) Recreate */$proj: \1 DRIFT (on-disk config differs; recreate to apply)/"
  done

section "Git: home-server repo"
git -C "$REPO" status --short | head -40
echo "uncommitted files: $(git -C "$REPO" status --short | wc -l)"
echo "unpushed commits: $(git -C "$REPO" log --oneline '@{u}..' 2>/dev/null | wc -l)"
echo "last commit: $(git -C "$REPO" log -1 --format='%h %ad %s' --date=short)"
for d in /home/jeff/llm /home/jeff/flightdensity; do
  git -C "$d" rev-parse 2>/dev/null && echo "$d: git repo" || echo "$d: NOT in git"
done
