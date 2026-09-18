#!/bin/sh
# Writes docker restart-count / state / health metrics for node-exporter's textfile
# collector. cAdvisor has none of these (its start_time is creation time, not last start).
set -u
OUT=${TEXTFILE_DIR:-/textfile}/docker.prom
INTERVAL=${INTERVAL:-30}
while true; do
  {
    echo '# HELP docker_container_restart_count Times dockerd restarted the container under its restart policy. Resets when recreated.'
    echo '# TYPE docker_container_restart_count gauge'
    echo '# HELP docker_container_state 1 for the container'"'"'s current state (running, exited, restarting, ...).'
    echo '# TYPE docker_container_state gauge'
    echo '# HELP docker_container_healthy 1 healthy, 0 unhealthy. Only for containers that define a healthcheck; absent while starting.'
    echo '# TYPE docker_container_healthy gauge'
    docker ps -aq | xargs -r docker inspect --format \
      '{{.Name}} {{.RestartCount}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    | awk '{
        n = substr($1, 2)
        printf "docker_container_restart_count{name=\"%s\"} %s\n", n, $2
        printf "docker_container_state{name=\"%s\",state=\"%s\"} 1\n", n, $3
        if ($4 == "healthy")   printf "docker_container_healthy{name=\"%s\"} 1\n", n
        if ($4 == "unhealthy") printf "docker_container_healthy{name=\"%s\"} 0\n", n
      }'
  } > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"   # atomic so node-exporter never reads a half-written file
  sleep "$INTERVAL"
done
