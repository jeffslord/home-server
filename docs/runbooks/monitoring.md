# Monitoring and alerting

Stack: `monitor/docker-compose.yaml` (Prometheus, Alertmanager, Grafana, Loki, Alloy,
node-exporter, cAdvisor, docker-state, GPU exporter, blackbox, ntfy).
Alert rules: `monitor/prometheus/rules/`. Routing: `monitor/alertmanager/config.yml`.
Phone formatting: `monitor/ntfy/templates/homeserver.yml`.

## "I'm not getting alerts"

```sh
docker logs --since 1h alertmanager 2>&1 | grep -iE 'fail|denied' | tail
```

Send a test alert (low priority, expires in 5 minutes):

```sh
curl -s -XPOST localhost:9093/api/v2/alerts -H 'Content-Type: application/json' -d '[{"labels":{"alertname":"AlertPathTest","severity":"info"},"annotations":{"summary":"test"},"endsAt":"'$(date -u -d '+5 min' +%FT%TZ)'"}]'
```

It should reach the phone within ~1 minute (topic `home_alerts`).

| Log says | Fix |
|---|---|
| `permission denied` on `/run/secrets/...` or `/alertmanager` | The container must run as uid 1000 (`user: "1000:1000"` in compose). This silently broke all alerts from 2026-09-30 to 2026-10-19. |
| `401`/`403` from ntfy | The `alertmanager` ntfy user lost access: `docker exec ntfy ntfy access alertmanager home_alerts wo` |
| No errors, nothing arrives | The phone isn't subscribed to `home_alerts`, or the alert is inhibited/grouped: http://localhost:9093 (via ssh tunnel) |

If eris is completely dead, none of this fires: healthchecks.io emails when the
Ofelia ping (every 5 min) stops.

## `TargetDown`

Prometheus can't scrape an exporter. `docker ps | grep <job>` → [containers.md](containers.md).
If the target is `prometheus` itself, check `docker logs prometheus` (often disk full: [host.md](host.md)).

## Changing rules

```sh
cd ~/development/github.com/home-server/monitor/prometheus/rules
docker run --rm --entrypoint promtool -v $PWD:/r:ro prom/prometheus:latest check rules /r/*.yml
docker exec prometheus kill -HUP 1          # reload
```

Give every alert a `runbook:` annotation (a path under `docs/runbooks/`). The ntfy template
turns it into a link.
Containers that are stopped by design are listed in three places; keep them in sync:
`rules/containers.yml`, `bin/health` (`IDLE`), `monitor/audit/collect.sh` (`ONE_SHOT`).
