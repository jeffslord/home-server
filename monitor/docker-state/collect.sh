#!/bin/sh
# Writes docker restart-count / state / health metrics for node-exporter's textfile
# collector. cAdvisor has none of these (its start_time is creation time, not last start).
set -u
OUT=${TEXTFILE_DIR:-/textfile}/docker.prom
INTERVAL=${INTERVAL:-30}
MANIFEST=${MANIFEST:-/manifest/running-images.tsv}
TAB=$(printf '\t')

# Which exact image every container runs, so a rebuild (docs/runbooks/disaster-recovery.md)
# can go back to the same versions even where compose says :latest. Backed up nightly by
# borgmatic, so its archives hold the history. Rewritten only when something changed.
manifest() {
  {
    echo "# container${TAB}compose_dir${TAB}image_as_configured${TAB}version_label${TAB}repo_digest (pin with image: <repo>@sha256:...)"
    docker ps -aq | xargs -r docker inspect --format \
      '{{slice .Name 1}}{{"\t"}}{{index .Config.Labels "com.docker.compose.project.working_dir"}}{{"\t"}}{{.Config.Image}}{{"\t"}}{{.Image}}' \
    | sort | while IFS="$TAB" read -r name dir ref id; do
      info=$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.version"}}{{"\t"}}{{join .RepoDigests ","}}' "$id" 2>/dev/null)
      printf '%s\t%s\t%s\t%s\n' "$name" "${dir:--}" "$ref" "${info:-?$TAB$id}"
    done
  } > "$MANIFEST.tmp"
  if cmp -s "$MANIFEST.tmp" "$MANIFEST"; then rm -f "$MANIFEST.tmp"; else mv "$MANIFEST.tmp" "$MANIFEST"; fi
}

loops=0
while true; do
  [ $((loops % 20)) -eq 0 ] && [ -d "$(dirname "$MANIFEST")" ] && manifest   # every ~10 min
  loops=$((loops + 1))
  {
    echo '# HELP docker_container_restart_count Times dockerd restarted the container under its restart policy. Resets when recreated.'
    echo '# TYPE docker_container_restart_count gauge'
    echo '# HELP docker_container_state 1 for the container'"'"'s current state (running, exited, restarting, ...).'
    echo '# TYPE docker_container_state gauge'
    echo '# HELP docker_container_healthy 1 healthy, 0 unhealthy. Only for containers that define a healthcheck; absent while starting.'
    echo '# TYPE docker_container_healthy gauge'
    echo '# HELP docker_container_exit_code Exit code of the last run. Only for containers that are not running.'
    echo '# TYPE docker_container_exit_code gauge'
    docker ps -aq | xargs -r docker inspect --format \
      '{{.Name}} {{.RestartCount}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.State.ExitCode}}' \
    | awk '{
        n = substr($1, 2)
        printf "docker_container_restart_count{name=\"%s\"} %s\n", n, $2
        printf "docker_container_state{name=\"%s\",state=\"%s\"} 1\n", n, $3
        if ($4 == "healthy")   printf "docker_container_healthy{name=\"%s\"} 1\n", n
        if ($4 == "unhealthy") printf "docker_container_healthy{name=\"%s\"} 0\n", n
        if ($3 != "running")   printf "docker_container_exit_code{name=\"%s\"} %s\n", n, $5
      }'
  } > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"   # atomic so node-exporter never reads a half-written file
  sleep "$INTERVAL"
done
