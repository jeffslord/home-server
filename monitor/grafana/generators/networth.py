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


# --- Projection -------------------------------------------------------------------
# Month-by-month compounding from today's balances, in SQL (recursive CTE), driven by
# dashboard variables. Annual nominal rates per scenario; the fan chart draws all three.
SCENARIOS = [  # (name, stocks, cash, home)
    ("Conservative", 0.05, 0.02, 0.02),
    ("Base", 0.07, 0.03, 0.03),
    ("Optimistic", 0.09, 0.04, 0.04),
]
SCEN_COLOR = {"Conservative": "#e66767", "Base": NET_WORTH_INK, "Optimistic": "#3987e5"}
INFLATION = 0.025   # contributions rise with it; "Today's dollars" divides it back out
# 401(k) ~$950 + match ~$500 + Roth IRA $7,500/yr + HSA $4,400/yr (2026 self-only limit)
RETIRE_MONTHLY = 2450
PROJ_MONTHS = 30 * 12
mo = lambda annual: (1 + annual) ** (1 / 12) - 1


def included(t):  # 1 unless the Exclude dropdown drops export type t
    return f"(instr('|' || '${{exclude}}' || '|', '|{t}|') = 0)"


# Mortgage, credit cards and vehicles stay at today's balance ("fixed"): Actual does
# not track mortgage paydown. HSA counts as retirement money.
PROJ = (
    "p(scen, r, c, h) AS (VALUES "
    + ", ".join(f"('{n}', {mo(s)!r}, {mo(c)!r}, {mo(h)!r})" for n, s, c, h in SCENARIOS) + "), "
    "s AS (SELECT SUM(CASE WHEN type = 'Cash' THEN balance ELSE 0 END) AS cash, "
    "SUM(CASE WHEN type = 'Investments' THEN balance ELSE 0 END) AS inv, "
    "SUM(CASE WHEN type IN ('Retirement', 'HSA') THEN balance ELSE 0 END) AS ret, "
    "SUM(CASE WHEN type = 'Real estate' AND balance > 0 THEN balance ELSE 0 END) AS house, "
    "SUM(balance) AS total FROM accounts WHERE 1 = 1" + TF + "), "
    "f AS (SELECT CAST('${extra}' AS REAL) * " + included("Investments") + " AS extra, "
    "CAST('${retire}' AS REAL) * " + included("Retirement") + " AS retc, "
    f"CAST('${{dollars}}' AS REAL) AS defl, {1 + mo(INFLATION)!r} AS infl, "
    "julianday((SELECT MAX(date) FROM balances)) AS start), "
    "proj(scen, m, cash, inv, ret, house, fixed, grow, dfl) AS ("
    "SELECT scen, 0, cash, inv, ret, house, total - cash - inv - ret - house, 1.0, 1.0 FROM p, s "
    "UNION ALL SELECT proj.scen, m + 1, cash * (1 + c), inv * (1 + r) + extra * grow, "
    "ret * (1 + r) + retc * grow, house * (1 + h), fixed, grow * infl, dfl * defl "
    f"FROM proj JOIN p ON p.scen = proj.scen, f WHERE m < {PROJ_MONTHS}), "
    # month m as epoch ms, anchored on the latest exported day
    "pt AS (SELECT proj.*, (julianday((SELECT MAX(date) FROM balances), '+' || m || ' months') "
    "- 2440587.5) * 86400000 AS t, (cash + inv + ret + house + fixed) * dfl AS nw FROM proj)"
)

panels.append({"type": "row", "title": "Projection", "collapsed": False,
               "gridPos": {"x": 0, "y": 44, "w": 24, "h": 1}, "panels": []})

YEARS = [5, 10, 20, 30]
panels.append(panel(
    "stat", "Projected net worth · ${scenario}", 0, 45, 24, 4,
    f"WITH {PROJ} SELECT "
    + ", ".join(f"MAX(CASE WHEN m = {y * 12} THEN nw END) AS \"In {y} years\"" for y in YEARS)
    + " FROM pt WHERE scen = '${scenario}'", fmt="table",
    defaults={**MONEY, "decimals": 2, "color": {"mode": "fixed", "fixedColor": NET_WORTH_INK}},
    options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""}, "colorMode": "none",
             "graphMode": "none", "textMode": "value_and_name", "justifyMode": "center",
             "text": {"titleSize": 13, "valueSize": 24}},
    desc="Net worth at each horizon for the scenario picked in the Scenario dropdown."))

rates = "; ".join(f"{n} {s:.0%} stocks, {c:.0%} cash, {h:.0%} home" for n, s, c, h in SCENARIOS)
ASSUMPTIONS = (f"Annual nominal returns: {rates}. Contributions rise {INFLATION:.1%}/yr. "
               "Retirement $/mo goes to retirement accounts, Brokerage $/mo to investments. "
               "Mortgage, credit cards and vehicles stay at today's balance.")
TREND = {"unit": "currencyUSD",
         "custom": {"lineWidth": 2, "fillOpacity": 0, "showPoints": "never", "spanNulls": True,
                    "lineInterpolation": "linear"}}
# x is epoch ms shown as years; the $ axes start at 0 (a y-only override, since
# field defaults would also pin the x axis to 1970)
X_AXIS = {"matcher": {"id": "byName", "options": "time"},
          "properties": [{"id": "unit", "value": "time:YYYY"}]}
Y_ZERO = {"matcher": {"id": "byRegexp", "options": "^(?!time$).*"},
          "properties": [{"id": "custom.axisSoftMin", "value": 0}]}
HORIZON = "m <= ${horizon} * 12"

# Trend panel (numeric x) rather than timeseries: a time series is clipped to the
# dashboard's time range, which ends at now.
panels.append(panel(
    "trend", "Net worth projection", 0, 49, 14, 11,
    f"WITH {PROJ}, hist AS (SELECT time * 1000 AS t, SUM(balance) AS v FROM balances "
    f"WHERE date >= '2025-10-01' AND strftime('%d', date) = '01'{TF} GROUP BY date) "
    "SELECT t AS time, v AS \"Actual\", NULL AS \"Conservative\", NULL AS \"Base\", NULL AS \"Optimistic\" "
    "FROM hist UNION ALL SELECT t, NULL, "
    + ", ".join(f"MAX(CASE WHEN scen = '{n}' THEN nw END)" for n, *_ in SCENARIOS)
    + f" FROM pt WHERE {HORIZON} GROUP BY m ORDER BY time", fmt="table",
    defaults=TREND,
    overrides=[X_AXIS, Y_ZERO, color_override("Actual")]
    + [{"matcher": {"id": "byName", "options": n},
        "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": SCEN_COLOR[n]}},
                       {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 6]}}]}
       for n, *_ in SCENARIOS],
    options={"xField": "time", "legend": {"displayMode": "list", "placement": "bottom"},
             "tooltip": {"mode": "multi", "sort": "desc"}},
    desc="Monthly net worth since October 2025 (the house value was added to Actual in mid-September), then all three scenarios out to the Horizon. " + ASSUMPTIONS))

PROJ_TYPES = [("Cash", "cash"), ("Investments", "inv"), ("Retirement", "ret"),
              ("Home equity", "house + fixed")]   # fixed (mortgage, cards) nets against the house
panels.append(panel(
    "trend", "Projection by type · ${scenario}", 14, 49, 10, 11,
    f"WITH {PROJ} SELECT t AS time, "
    + ", ".join(f"({e}) * dfl AS \"{a}\"" for a, e in PROJ_TYPES)
    + f" FROM pt WHERE scen = '${{scenario}}' AND {HORIZON} ORDER BY m", fmt="table",
    defaults={**TREND, "custom": {**TREND["custom"], "lineWidth": 0, "fillOpacity": 70,
                                  "stacking": {"mode": "normal", "group": "A"}}},
    overrides=[X_AXIS, Y_ZERO] + [color_override(a) for a, _ in PROJ_TYPES],
    options={"xField": "time", "legend": {"displayMode": "list", "placement": "bottom"},
             "tooltip": {"mode": "multi", "sort": "none"}},
    desc="The picked scenario stacked by type. " + ASSUMPTIONS))

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
        "current": {"text": "None", "value": "__none"}},
        # Projection inputs (only the Projection row uses them)
        {"name": "scenario", "label": "Scenario", "type": "custom", "multi": False, "includeAll": False,
         "query": ", ".join(n for n, *_ in SCENARIOS), "current": {"text": "Base", "value": "Base"}},
        {"name": "horizon", "label": "Horizon (years)", "type": "custom", "multi": False, "includeAll": False,
         "query": ", ".join(map(str, YEARS)), "current": {"text": "20", "value": "20"}},
        {"name": "retire", "label": "Retirement $/mo", "type": "textbox", "query": str(RETIRE_MONTHLY),
         "current": {"text": str(RETIRE_MONTHLY), "value": str(RETIRE_MONTHLY)}},
        {"name": "extra", "label": "Brokerage $/mo", "type": "textbox", "query": "0",
         "current": {"text": "0", "value": "0"}},
        {"name": "dollars", "label": "Dollars", "type": "custom", "multi": False, "includeAll": False,
         # value = monthly deflator applied to every projected month
         "query": f"Nominal : 1, Today's : {1 / (1 + mo(INFLATION))!r}",
         "current": {"text": "Nominal", "value": "1"}}]},
    "panels": panels,
}

out = os.path.join(os.path.dirname(__file__), "..", "dashboards", "finance", "networth.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump(dash, f, indent=2)
    f.write("\n")
print("wrote", os.path.normpath(out))
