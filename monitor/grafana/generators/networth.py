#!/usr/bin/env python3
"""Generates ../dashboards/finance/networth.json. Edit this, not the JSON.
   python3 monitor/grafana/generators/networth.py

Data: finance/helpers/networth-export.js writes Actual balances (per account per
day, with an account type derived from the name's emoji) to a SQLite file that
the "Actual net worth" datasource (frser-sqlite-datasource) reads."""
import json, os

DS = {"type": "frser-sqlite-datasource", "uid": "actual-networth"}

# Fixed categorical order (dark-theme steps of the dataviz reference palette);
# a type keeps its color no matter which others are present.
TYPES = [  # (column alias, type in the export, color)
    ("Cash", "Cash", "#3987e5"),
    ("Investments", "Investments", "#d95926"),
    ("Retirement", "Retirement", "#199e70"),
    ("HSA", "HSA", "#c98500"),
    ("Home equity", "Real estate", "#d55181"),
    ("Vehicles", "Vehicles", "#008300"),
    ("Credit cards", "Credit cards", "#9085e9"),
]
# HSA is left out: the open HSA (Fidelity) counts as Retirement by choice, and the
# closed Anthem HSA only shows up in the history chart.
ASSETS = ["Cash", "Investments", "Retirement", "Home equity"]
COLOR = {alias: c for alias, _, c in TYPES}
NET_WORTH_INK = "#c3c2b7"   # neutral: net worth is a total, not a type
RANGE = "time >= $__from / 1000 AND time < $__to / 1000"
# The "Exclude" dropdown (single-select dashboard variable `exclude`, default None): every
# panel except the per-type tiles leaves out the picked type(s). A value is a |-separated
# list of export types, so presets can combine several.
TF = " AND instr('|' || '${exclude}' || '|', '|' || type || '|') = 0"
EXCLUDE = [("None", "__none"), *((a, t) for a, t, _ in TYPES if a not in ("HSA", "Vehicles")),
           ("Home equity + Retirement", "Real estate|Retirement")]


def pivot(cols):
    return ", ".join(f"SUM(CASE WHEN type = '{t}' THEN balance ELSE 0 END) AS \"{a}\""
                     for a, t, _ in TYPES if a in cols)


def target(sql, fmt="time series"):
    t = {"refId": "A", "datasource": DS, "queryText": sql, "rawQueryText": sql, "queryType": fmt}
    if fmt == "time series":
        t["timeColumns"] = ["time"]
    return t


def color_override(name, extra=()):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": COLOR.get(name, NET_WORTH_INK)}},
                           *extra]}


def panel(type_, title, x, y, w, h, sql, fmt="time series", defaults=None, overrides=None, options=None, desc=None):
    p = {"type": type_, "title": title, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [target(sql, fmt)],
         "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
         "options": options or {}}
    if desc:
        p["description"] = desc
    return p


MONEY = {"unit": "currencyUSD", "decimals": 0}


def stat(title, x, w, where, color, big=False, desc=None, trend=True):
    sql = (f"SELECT time, SUM(balance) AS value FROM balances WHERE {RANGE}{where} "
           "GROUP BY time ORDER BY time")
    return panel("stat", title, x, 0, w, 5, sql,
                 # min 0: the trend line shows real proportions instead of autoscaled noise
                 defaults={**MONEY, **({"decimals": 2} if big else {}), **({"min": 0} if trend else {}),
                           "color": {"mode": "fixed", "fixedColor": color}},
                 options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""},
                          "colorMode": "none", "graphMode": "area" if trend else "none", "textMode": "value",
                          "justifyMode": "center", "text": {"valueSize": 40 if big else 26}},
                 desc=desc)


panels = [stat("Net worth", 0, 9, TF, NET_WORTH_INK, big=True,
               desc="Sum of every account in Actual (on and off budget) at the end of the range.")]
x = 9
for alias, t, c in TYPES:
    if alias in ("HSA", "Vehicles"):   # closed accounts only; still part of the history chart
        continue
    panels.append(stat(alias, x, 3, f" AND type = '{t}'", c, trend=alias != "Credit cards",
                       desc="House value minus mortgage." if alias == "Home equity" else None))
    x += 3

# Change panels are relative to the latest exported day, not the time picker.
# Diverging pair (dark steps): gain blue, loss red, never hue alone (sign is in the value).
GAIN, LOSS = "#3987e5", "#e66767"
SIGNED = {"color": {"mode": "thresholds"},
          "thresholds": {"mode": "absolute", "steps": [{"color": LOSS, "value": None}, {"color": GAIN, "value": 0}]}}
NW = f"nw AS (SELECT date, time, SUM(balance) AS v FROM balances WHERE 1 = 1{TF} GROUP BY date)"
PERIODS = [("30 days", "'-30 days'"), ("90 days", "'-90 days'"), ("YTD", "'start of year', '-1 day'"),
           ("12 months", "'-1 year'")]


def at(offset):  # net worth on the last exported day on/before (latest day + offset)
    return (f"(SELECT v FROM nw WHERE date <= date((SELECT MAX(date) FROM nw), {offset}) "
            "ORDER BY date DESC LIMIT 1)")


NOW = "(SELECT v FROM nw ORDER BY date DESC LIMIT 1)"


def change_stat(title, x, w, expr, unit, decimals, desc):
    cols = ", ".join(f"{expr.format(now=NOW, then=at(o))} AS \"{n}\"" for n, o in PERIODS)
    return panel("stat", title, x, 5, w, 4, f"WITH {NW} SELECT {cols}", fmt="table",
                 defaults={"unit": unit, "decimals": decimals, **SIGNED},
                 options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}, "colorMode": "value",
                          "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center",
                          "text": {"titleSize": 13, "valueSize": 24}},
                 desc=desc)


panels.append(change_stat("Net worth change", 0, 14, "{now} - {then}", "currencyUSD", 0,
                          "Change up to the latest exported day. YTD compares with Dec 31. "
                          "Ignores the time picker."))
panels.append(change_stat("Net worth change %", 14, 10, "({now} - {then}) / ABS({then})", "percentunit", 1,
                          "Same periods as a share of net worth at the start of each period."))

# One bar per calendar month: month-end net worth minus the previous month-end.
panels.append(panel(
    "barchart", "Monthly change", 0, 20, 12, 9,
    f"WITH {NW}, ends AS (SELECT MAX(date) AS d FROM nw GROUP BY strftime('%Y-%m', date)), "
    "m AS (SELECT nw.date AS day, nw.time, nw.v - LAG(nw.v) OVER (ORDER BY nw.date) AS delta "
    "FROM ends JOIN nw ON nw.date = ends.d) "
    # short labels so they fit on a phone: "Oct", year only on January ("Jan ’26")
    "SELECT substr('JanFebMarAprMayJunJulAugSepOctNovDec', CAST(strftime('%m', day) AS INTEGER) * 3 - 2, 3) "
    "|| CASE strftime('%m', day) WHEN '01' THEN ' ’' || substr(strftime('%Y', day), 3) ELSE '' END "
    "AS \"Month\", delta AS \"Change\" FROM m "
    f"WHERE delta IS NOT NULL AND {RANGE} ORDER BY day", fmt="table",
    defaults={**MONEY, **SIGNED, "custom": {"fillOpacity": 90, "lineWidth": 0, "axisSoftMin": 0,
                                            "axisCenteredZero": False}},
    options={"xField": "Month", "orientation": "vertical", "showValue": "never", "barWidth": 0.8,
             "groupWidth": 0.7, "legend": {"showLegend": False}, "tooltip": {"mode": "single"},
             "xTickLabelRotation": 0, "xTickLabelSpacing": 40},  # >0 lets Grafana skip labels when narrow
    desc="Month-end net worth minus the previous month-end (the current month is month-to-date). "
         "Last 12 months: earlier history has accounts that were only added to Actual later."))
panels[-1].update(timeFrom="11M", hideTimeOverride=True)  # 11M back = the last 12 month-ends

share_total = " + ".join(f'"{a}"' for a in ASSETS)
share_cols = ", ".join(f'"{a}" / ({share_total}) AS "{a}"' for a in ASSETS)
panels.append(panel(
    "timeseries", "Asset mix", 12, 20, 12, 9,
    # shares computed in SQL (not percent stacking) so the tooltip shows percentages
    f"SELECT time, {share_cols} FROM (SELECT time, {pivot(ASSETS)} FROM balances WHERE {RANGE}{TF} "
    "GROUP BY time) ORDER BY time",
    defaults={"unit": "percentunit", "decimals": 0, "min": 0, "max": 1,
              "custom": {"stacking": {"mode": "normal", "group": "A"}, "fillOpacity": 80, "lineWidth": 0,
                         "drawStyle": "line", "lineInterpolation": "stepAfter", "showPoints": "never"}},
    overrides=[color_override(a) for a in ASSETS],
    options={"legend": {"displayMode": "list", "placement": "bottom"},
             "tooltip": {"mode": "multi", "sort": "desc"}},
    desc="Share of each asset type over the last 12 months (credit cards and vehicles left out)."))
panels[-1]["timeFrom"] = "1y"

panels.append(panel(
    "piechart", "Assets by type", 0, 9, 10, 11,
    f"SELECT {pivot(ASSETS)} FROM accounts WHERE closed = 0{TF}", fmt="table",
    defaults=MONEY, overrides=[color_override(a) for a in ASSETS],
    options={"pieType": "donut", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
             "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
             "displayLabels": ["percent"], "tooltip": {"mode": "single"}},
    desc="Current balances of open accounts. Credit-card debt is left out of the donut (it is in net worth)."))

type_case = " ".join(f"WHEN '{t}' THEN '{a}'" for a, t, _ in TYPES)
type_order = " ".join(f"WHEN '{t}' THEN {i}" for i, (_, t, _) in enumerate(TYPES))
panels.append(panel(
    "table", "Accounts", 10, 9, 14, 11,
    # Balance twice: the amount as text, then as a bar in the last column. The bar
    # column has no fixed width, so on a phone it shrinks instead of pushing the
    # amounts off-screen.
    f"SELECT CASE type {type_case} ELSE type END AS \"Type\", name AS \"Account\", balance AS \"Balance\", "
    f"balance AS \"Share\" FROM accounts WHERE closed = 0 AND ABS(balance) >= 1{TF} "
    f"ORDER BY CASE type {type_order} ELSE 99 END, balance DESC", fmt="table",
    defaults={"unit": "currencyUSD", "decimals": 0, "custom": {"filterable": False}},
    overrides=[{"matcher": {"id": "byName", "options": "Balance"},
                "properties": [{"id": "custom.align", "value": "right"}, {"id": "custom.width", "value": 95}]},
               {"matcher": {"id": "byName", "options": "Share"},
                "properties": [{"id": "displayName", "value": " "}, {"id": "min", "value": 0},
                               {"id": "custom.minWidth", "value": 40},
                               {"id": "color", "value": {"mode": "fixed", "fixedColor": NET_WORTH_INK}},
                               {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic",
                                                                      "valueDisplayMode": "hidden"}}]},
               {"matcher": {"id": "byName", "options": "Type"},
                "properties": [{"id": "custom.width", "value": 100}]}],
    options={"showHeader": True, "cellHeight": "sm"}))

history_cols = [a for a, _, _ in TYPES]
panels.append(panel(
    "timeseries", "Balance by type over time", 0, 29, 24, 12,
    f"SELECT time, {pivot(history_cols)}, SUM(balance) AS \"Net worth\" FROM balances "
    f"WHERE {RANGE}{TF} GROUP BY time ORDER BY time",
    defaults={"unit": "currencyUSD",
              "custom": {"stacking": {"mode": "normal", "group": "A"}, "fillOpacity": 70, "lineWidth": 0,
                         "drawStyle": "line", "lineInterpolation": "stepAfter", "showPoints": "never"}},
    overrides=[color_override(a) for a in history_cols] + [color_override("Net worth", [
        {"id": "custom.stacking", "value": {"mode": "none", "group": "nw"}},
        {"id": "custom.fillOpacity", "value": 0}, {"id": "custom.lineWidth", "value": 2}])],
    options={"legend": {"displayMode": "list", "placement": "bottom"},
             "tooltip": {"mode": "multi", "sort": "none"}},
    desc="Stacked daily balances per type (negative types stack below zero); the line is net worth. "
         "Investment history moves in steps: Actual only records the daily balance adjustments."))

panels.append(panel(
    "stat", "Exported", 0, 41, 6, 3,
    "SELECT CAST(value AS INTEGER) * 1000 AS \"Exported\" FROM meta WHERE key = 'updated_at'", fmt="table",
    defaults={"unit": "dateTimeFromNow", "color": {"mode": "fixed", "fixedColor": NET_WORTH_INK}},
    options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}, "colorMode": "none",
             "graphMode": "none", "textMode": "value", "text": {"valueSize": 18}},
    desc="When networth-export.js last ran (hourly Ofelia job actual-networth, or Refresh now)."))

# /actual-refresh is networth-refresh.js (finance/helpers), routed by Caddy on this
# host: it runs the export and redirects back here. target="_self" matters: Grafana
# routes target-less same-origin links inside its SPA, which would 404.
panels.append({
    "type": "text", "title": "", "transparent": True,
    "gridPos": {"x": 6, "y": 41, "w": 4, "h": 3},
    "options": {"mode": "html", "content": (
        '<div style="display:flex;height:100%;align-items:center">'
        '<a href="/actual-refresh" target="_self" title="Re-read Actual now (takes a few seconds)" '
        'style="padding:6px 14px;border:1px solid currentColor;border-radius:4px;'
        'text-decoration:none;font-weight:500">&#x21bb; Refresh now</a></div>')},
})

for i, p in enumerate(panels, 1):  # stable ids for panel links (d-solo, viewPanel)
    p["id"] = i

dash = {
    "uid": "actual-networth",
    "title": "Net worth",
    "tags": ["finance", "actual"],
    "timezone": "browser",
    "schemaVersion": 41,
    "time": {"from": "2023-02-01T00:00:00.000Z", "to": "now"},
    "refresh": "",
    "templating": {"list": [{
        "name": "exclude", "label": "Exclude", "type": "custom", "multi": False, "includeAll": False,
        "query": ", ".join(f"{a} : {v}" for a, v in EXCLUDE),  # "label : value" pairs
        "current": {"text": "None", "value": "__none"}}]},
    "panels": panels,
}

out = os.path.join(os.path.dirname(__file__), "..", "dashboards", "finance", "networth.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump(dash, f, indent=2)
    f.write("\n")
print("wrote", os.path.normpath(out))
