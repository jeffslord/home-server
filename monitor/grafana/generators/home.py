#!/usr/bin/env python3
"""Generates ../dashboards/home.json. Edit this, not the JSON.
   python3 monitor/grafana/generators/home.py"""
import json, os

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
GREEN, ORANGE, RED, BLUE, TEXT = "green", "orange", "red", "blue", "text"

def thresholds(*steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}

def panel(type_, title, x, y, w, h, targets, unit=None, thr=None, mappings=None,
          options=None, overrides=None, decimals=None, min_=None, max_=None, desc=None):
    defaults = {}
    if unit: defaults["unit"] = unit
    if thr: defaults["thresholds"] = thr
    if mappings: defaults["mappings"] = mappings
    if decimals is not None: defaults["decimals"] = decimals
    if min_ is not None: defaults["min"] = min_
    if max_ is not None: defaults["max"] = max_
    p = {"type": type_, "title": title, "datasource": PROM,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [dict(refId=chr(65 + i), datasource=PROM, **t) for i, t in enumerate(targets)],
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if desc: p["description"] = desc
    return p

def q(expr, legend=None, instant=False, fmt=None):
    t = {"expr": expr}
    if legend: t["legendFormat"] = legend
    if instant: t["instant"] = True; t["range"] = False
    if fmt: t["format"] = fmt
    return t

def stat(title, x, y, w, h, expr, unit=None, thr=None, legend=None, decimals=None,
         color_mode="value", graph=False, text_mode="auto", mappings=None, desc=None):
    return panel("stat", title, x, y, w, h, [q(expr, legend, instant=not graph)], unit=unit,
                 thr=thr or thresholds((TEXT, None)), decimals=decimals, mappings=mappings, desc=desc,
                 options={"colorMode": color_mode, "graphMode": "area" if graph else "none",
                          "textMode": text_mode, "justifyMode": "center", "wideLayout": True,
                          "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}})

def gauge(title, x, y, w, h, expr, legend=None, thr=None, unit="percent"):
    return panel("gauge", title, x, y, w, h, [q(expr, legend, instant=True)], unit=unit,
                 thr=thr or thresholds((GREEN, None), (ORANGE, 80), (RED, 90)), min_=0, max_=100, decimals=0,
                 options={"showThresholdMarkers": True, "showThresholdLabels": False,
                          "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}})

def timeseries(title, x, y, w, h, targets, unit=None, min_=None, max_=None, legend=True, fill=0, thr=None):
    p = panel("timeseries", title, x, y, w, h, targets, unit=unit, min_=min_, max_=max_, thr=thr,
              options={"legend": {"displayMode": "list" if legend else "hidden", "placement": "bottom", "showLegend": legend},
                       "tooltip": {"mode": "multi", "sort": "desc"}})
    p["fieldConfig"]["defaults"]["custom"] = {"lineWidth": 1, "fillOpacity": fill, "pointSize": 4,
                                              "showPoints": "never", "spanNulls": True, "gradientMode": "none"}
    p["fieldConfig"]["defaults"]["color"] = {"mode": "palette-classic"}
    return p

def bargauge(title, x, y, w, h, expr, legend, unit, thr=None, desc=None):
    return panel("bargauge", title, x, y, w, h, [q(expr, legend, instant=True)], unit=unit, desc=desc,
                 thr=thr or thresholds((BLUE, None)), min_=0, decimals=1,
                 options={"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                          "namePlacement": "left", "sizing": "auto", "valueMode": "color",
                          "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}})

def table(title, x, y, w, h, expr, rename, hide=(), unit=None, thr=None, desc=None, sort=None, decimals=None):
    p = panel("table", title, x, y, w, h, [q(expr, instant=True, fmt="table")], unit=unit, thr=thr, desc=desc, decimals=decimals,
              options={"showHeader": True, "cellHeight": "sm",
                       "sortBy": [{"displayName": sort, "desc": True}] if sort else []})
    exclude = {h: True for h in ("Time", "__name__", "job", "instance", *hide)}
    p["transformations"] = [{"id": "organize", "options": {"excludeByName": exclude, "renameByName": rename}}]
    return p

def logs(title, x, y, w, h, expr, desc=None):
    return {"type": "logs", "title": title, "datasource": LOKI, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "description": desc,
            "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "maxLines": 200}],
            "options": {"showTime": True, "showLabels": False, "showCommonLabels": False, "wrapLogMessage": True,
                        "prettifyLogMessage": False, "enableLogDetails": True, "dedupStrategy": "none", "sortOrder": "Descending"}}

def loki_timeseries(title, x, y, w, h, expr, legend, unit=None):
    p = timeseries(title, x, y, w, h, [q(expr, legend)], unit=unit, min_=0, fill=15)
    p["datasource"] = LOKI
    for t in p["targets"]: t["datasource"] = LOKI
    p["fieldConfig"]["defaults"]["custom"]["drawStyle"] = "bars"
    p["fieldConfig"]["defaults"]["custom"]["stacking"] = {"mode": "normal"}
    return p

def row(title, y):
    return {"type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}

updown = [{"type": "value", "options": {"0": {"text": "DOWN", "color": RED, "index": 0},
                                        "1": {"text": "UP", "color": GREEN, "index": 1}}}]

panels = []
# ---- Status ------------------------------------------------------------------
panels.append(row("Status", 0))
panels.append(stat("Firing alerts", 0, 1, 3, 4, 'count(ALERTS{alertstate="firing"}) or vector(0)',
                   thr=thresholds((GREEN, None), (RED, 1)), color_mode="background", decimals=0))
panels.append(table("Alerts", 3, 1, 12, 4, 'ALERTS{alertstate="firing"}',
                    rename={"alertname": "Alert", "severity": "Severity", "service": "Service", "name": "Container",
                            "mountpoint": "Mount"}, hide=("alertstate", "Value", "fstype", "device", "group"),
                    desc="Pending alerts are not shown; only what has actually fired."))
panels.append(stat("Cert expiry (min)", 15, 1, 3, 4, 'min((probe_ssl_earliest_cert_expiry - time()) / 86400)',
                   unit="d", decimals=0, thr=thresholds((RED, None), (ORANGE, 14), (GREEN, 21)),
                   desc="Days until the soonest-expiring Let's Encrypt cert. Caddy renews at 30 days."))
panels.append(stat("Uptime", 18, 1, 3, 4, "time() - node_boot_time_seconds", unit="dtdurations", decimals=0))
panels.append(stat("Containers", 21, 1, 3, 4, 'count(count by (name) (container_last_seen{name!=""}))', decimals=0))
panels.append(stat("Services (probed on the docker network)", 0, 5, 12, 7,
                   'probe_success{job="blackbox-internal"}', legend="{{service}}", mappings=updown,
                   color_mode="background", text_mode="name", desc="Green = the app answers HTTP. blackbox-internal job."))
panels.append(stat("Public routes (DNS → Caddy → Authentik)", 12, 5, 12, 7,
                   'probe_success{job="blackbox-external"}', legend="{{service}}", mappings=updown,
                   color_mode="background", text_mode="name",
                   desc="Green = reachable from outside like a browser. If an app is UP here but DOWN on the left, the app is broken; the reverse means Caddy/DNS/router."))

# ---- Host --------------------------------------------------------------------
Y = 12
panels.append(row("Host", Y))
panels.append(gauge("CPU", 0, Y+1, 4, 5, '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))'))
panels.append(gauge("Memory", 4, Y+1, 4, 5, "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"))
panels.append(gauge("Root disk", 8, Y+1, 4, 5, '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
                    thr=thresholds((GREEN, None), (ORANGE, 85), (RED, 95))))
panels.append(stat("CPU temp", 12, Y+1, 2, 5, 'node_hwmon_temp_celsius{chip="platform_coretemp_0", sensor="temp1"}',
                   unit="celsius", decimals=0, thr=thresholds((GREEN, None), (ORANGE, 75), (RED, 90))))
panels.append(stat("NVMe temp", 14, Y+1, 2, 5, 'max(node_hwmon_temp_celsius{chip=~"nvme.*"})',
                   unit="celsius", decimals=0, thr=thresholds((GREEN, None), (ORANGE, 65), (RED, 75))))
panels.append(timeseries("CPU & memory", 16, Y+1, 8, 5, [
    q('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))', "cpu"),
    q("100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)", "memory")],
    unit="percent", min_=0, max_=100))

# ---- NAS ---------------------------------------------------------------------
Y = 18
panels.append(row("NAS (unraid, NFS)", Y))
panels.append(gauge("NAS shares used", 0, Y+1, 12, 6,
                    '100 * (1 - node_filesystem_avail_bytes{fstype="nfs4"} / node_filesystem_size_bytes{fstype="nfs4"})',
                    legend="{{mountpoint}}", thr=thresholds((GREEN, None), (ORANGE, 90), (RED, 95))))
panels.append(timeseries("Ping latency", 12, Y+1, 12, 6,
                         [q('probe_duration_seconds{job="blackbox-icmp"}', "{{name}}")], unit="s", min_=0))

# ---- Containers --------------------------------------------------------------
Y = 25
panels.append(row("Containers", Y))
panels.append(bargauge("Top memory", 0, Y+1, 6, 8,
                       'topk(10, sum by (name) (container_memory_working_set_bytes{name!=""}))', "{{name}}", "bytes"))
panels.append(bargauge("Top CPU", 6, Y+1, 6, 8,
                       'topk(10, sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m])) * 100)', "{{name}}", "percent",
                       desc="100% = one full core."))
panels.append(table("Restarts (24h)", 12, Y+1, 6, 8, 'increase(docker_container_restart_count[24h]) > 0',
                    rename={"name": "Container", "Value": "Restarts"}, sort="Restarts", decimals=0,
                    desc="Restarts by dockerd's restart policy. Empty is good."))
panels.append(stat("Healthchecks", 18, Y+1, 6, 8, "docker_container_healthy", legend="{{name}}",
                   mappings=[{"type": "value", "options": {"0": {"text": "UNHEALTHY", "color": RED, "index": 0},
                                                            "1": {"text": "OK", "color": GREEN, "index": 1}}}],
                   color_mode="background", text_mode="name",
                   desc="Only containers that define a Docker healthcheck appear here."))

# ---- GPU ---------------------------------------------------------------------
Y = 34
panels.append(row("GPU (GTX 1080)", Y))
panels.append(stat("Temperature", 0, Y+1, 3, 3, "nvidia_smi_temperature_gpu", unit="celsius", decimals=0,
                   thr=thresholds((GREEN, None), (ORANGE, 75), (RED, 85))))
panels.append(stat("Utilization", 3, Y+1, 3, 3, "nvidia_smi_utilization_gpu_ratio * 100", unit="percent", decimals=0))
panels.append(stat("VRAM used", 0, Y+4, 3, 3, "nvidia_smi_memory_used_bytes", unit="bytes", decimals=1,
                   thr=thresholds((TEXT, None), (ORANGE, 7.5e9))))
panels.append(stat("Power", 3, Y+4, 3, 3, "nvidia_smi_power_draw_watts", unit="watt", decimals=0))
panels.append(timeseries("GPU utilization & VRAM", 6, Y+1, 18, 6, [
    q("nvidia_smi_utilization_gpu_ratio * 100", "utilization"),
    q("100 * nvidia_smi_memory_used_bytes / nvidia_smi_memory_total_bytes", "vram")],
    unit="percent", min_=0, max_=100))

# ---- Logs --------------------------------------------------------------------
Y = 41
panels.append(row("Logs (Loki)", Y))
panels.append(loki_timeseries("Errors per container", 0, Y+1, 12, 6,
    'topk(8, sum by (container) (count_over_time({job="docker", level=~"error|fatal|panic|critical"}[$__auto])))', "{{container}}"))
panels.append(loki_timeseries("Journal: warnings & errors by unit", 12, Y+1, 12, 6,
    'topk(8, sum by (unit) (count_over_time({job="journal", level=~"warn|err|crit|alert|emerg"}[$__auto])))', "{{unit}}"))
panels.append(logs("Recent container errors", 0, Y+7, 24, 10,
    '{job="docker", level=~"error|fatal|panic|critical"}',
    desc="All containers, last 200 error-level lines in the time range. Click a line for its labels; use Explore for a specific container."))

dashboard = {
    "uid": "home", "title": "Home", "tags": ["home"], "timezone": "browser", "editable": True,
    "graphTooltip": 1, "refresh": "30s", "time": {"from": "now-6h", "to": "now"}, "schemaVersion": 39,
    "panels": panels, "templating": {"list": []}, "annotations": {"list": []}, "links": [
        {"title": "Dashboards", "type": "dashboards", "asDropdown": True, "icon": "external link", "tags": ["community"]}],
}
out = os.path.join(os.path.dirname(__file__), "..", "dashboards", "home.json")
json.dump(dashboard, open(out, "w"), indent=2)
print(f"wrote {os.path.normpath(out)} ({len(panels)} panels)")
