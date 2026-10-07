#!/usr/bin/env bash
# Weekly server audit: collect a read-only snapshot, have Claude (headless, with NO
# tools, so it can only read the text it is given) write the report, save it and
# send the summary to ntfy. Run by the systemd user timer in ./systemd/.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
OUT=/home/jeff/volumes/audits                     # backed up by borgmatic
REPO=/home/jeff/development/github.com/home-server
NTFY_URL=https://ntfy.jeffslord.com/unraid
NTFY_TOKEN=$(grep -m1 '^NTFY_TOKEN=' "$REPO/monitor/offsite-backup/.env" | cut -d= -f2-)
export PATH="$HOME/.local/bin:$PATH"

mkdir -p "$OUT"
stamp=$(date +%F)
snapshot="$OUT/$stamp-snapshot.txt"
report="$OUT/$stamp-report.md"
previous=$(ls -1 "$OUT"/*-report.md 2>/dev/null | grep -v "$stamp" | tail -1)

notify() {  # notify <title> <priority 1-5> <tags> ; body on stdin
  local code
  code=$(curl -s -m 30 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $NTFY_TOKEN" \
    -H "Title: $1" -H "Priority: $2" -H "Tags: $3" --data-binary @- "$NTFY_URL")
  echo "ntfy publish \"$1\": HTTP $code"   # lands in `journalctl --user -u weekly-audit`
}

"$HERE/collect.sh" > "$snapshot" 2>&1

{
  cat "$HERE/prompt.md"
  printf '\n\n=== THIS WEEK: SNAPSHOT ===\n'
  cat "$snapshot"
  printf '\n\n=== LAST WEEK: REPORT ===\n'
  if [ -n "$previous" ]; then cat "$previous"; else echo "(none: this is the first audit)"; fi
} > "$OUT/$stamp-input.txt"

# --tools "" : no tools at all (no shell, no file access); --strict-mcp-config with no
# --mcp-config: no MCP servers either. The model only sees the text on stdin.
if ! timeout 900 claude -p --tools "" --strict-mcp-config --no-session-persistence \
      < "$OUT/$stamp-input.txt" > "$report" 2> "$OUT/$stamp-claude.err" || [ ! -s "$report" ]; then
  { echo "claude -p failed; the raw snapshot is in $snapshot"; tail -5 "$OUT/$stamp-claude.err"; } \
    | notify "Weekly server audit FAILED" 4 warning
  exit 1
fi
rm -f "$OUT/$stamp-input.txt" "$OUT/$stamp-claude.err"

status=$(grep -m1 '^STATUS:' "$report" | sed 's/^STATUS: *//')
case "$status" in
  OK*)              prio=2; tag=white_check_mark ;;
  ATTENTION*)       prio=3; tag=mag ;;
  *)                prio=4; tag=rotating_light ;;
esac
# Summary + top issues fit an ntfy message; the full report stays on disk.
sed -n '1,/^## Changes since last week/p' "$report" | grep -v '^## Changes' | head -c 3500 \
  | { cat; printf '\nFull report: %s\n' "$report"; } \
  | notify "Weekly audit: ${status%% —*}" "$prio" "$tag"

ls -1t "$OUT"/*-snapshot.txt 2>/dev/null | tail -n +13 | xargs -r rm -f   # keep ~3 months of snapshots
echo "audit written to $report"
