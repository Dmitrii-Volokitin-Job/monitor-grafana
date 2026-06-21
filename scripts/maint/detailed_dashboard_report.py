#!/usr/bin/env python3
"""Detailed per-dashboard report.

For every panel:
  - Run the underlying query against the live stack
  - Show row count + sample values
Reports any panel returning ERROR or 0 rows with the actual SQL/PromQL.
"""
import base64, json, os, urllib.parse, urllib.request
from pathlib import Path

GRAFANA = os.environ.get("GRAFANA", "http://localhost:3030")
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
DASH_DIR = Path(__file__).resolve().parent.parent.parent / "dashboards"


def substitute_vars(s):
    if not s: return s
    for k, v in {
        "$system_group": ".*", "${system_group}": ".*", "$system_group:singlequote": "'.*'",
        "$__interval": "5m", "$lab_group": ".*", "${lab_group}": ".*",
        "$node": ".*", "${node}": ".*",
        "$db": "monitor-postgres", "${db}": "monitor-postgres",
        "$datasource": "monitor-postgres", "${datasource}": "monitor-postgres",
        "$project_key": "customer-portal", "${project_key}": "customer-portal",
        "$environment": "base", "${environment}": "base",
        "$branch": "All", "${branch}": "All",
    }.items():
        s = s.replace(k, v)
    return s


def q_postgres(sql, fmt="table"):
    body = json.dumps({"queries": [{
        "refId": "A", "datasource": {"type": "postgres", "uid": "monitor-postgres"},
        "rawSql": substitute_vars(sql), "format": fmt,
    }], "from": "now-7d", "to": "now"}).encode()
    req = urllib.request.Request(f"{GRAFANA}/api/ds/query", data=body,
        headers={"Authorization": AUTH, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        a = d.get("results", {}).get("A", {})
        if a.get("status", 200) >= 400 or "error" in a:
            return None, a.get("error", "?")[:80]
        frames = a.get("frames", [])
        if not frames:
            return [], "no frames"
        cols = [f["name"] for f in frames[0]["schema"]["fields"]]
        rows = list(zip(*frames[0]["data"]["values"]))
        return (cols, rows), None
    except Exception as e:
        return None, str(e)[:80]


def q_prom(expr):
    qs = urllib.parse.urlencode({"query": substitute_vars(expr)})
    req = urllib.request.Request(
        f"{GRAFANA}/api/datasources/proxy/uid/monitor-prometheus/api/v1/query?{qs}",
        headers={"Authorization": AUTH})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        if d.get("status") != "success":
            return None, d.get("error", "?")[:80]
        res = d.get("data", {}).get("result", [])
        return res, None
    except Exception as e:
        return None, str(e)[:80]


def walk(o):
    if isinstance(o, list):
        for x in o: yield from walk(x)
    elif isinstance(o, dict):
        if "type" in o and "targets" in o: yield o
        for v in o.values(): yield from walk(v)


def fmt_sample(result):
    """Format first row of query result for compact display."""
    if isinstance(result, tuple):
        cols, rows = result
        if not rows: return "0 rows"
        first = rows[0]
        return f"{len(rows)} row(s); first: " + ", ".join(
            f"{c}={str(v)[:30]}" for c, v in zip(cols, first)
        )[:160]
    elif isinstance(result, list):
        if not result: return "0 series"
        first = result[0]
        return f"{len(result)} series; first: {first.get('metric',{})} value={first.get('value',['?','?'])[1]}"
    return "?"


def main():
    files = sorted(DASH_DIR.glob("*.json"))
    for f in files:
        data = json.loads(f.read_text())
        title = data.get("title", f.name)
        print(f"\n{'='*72}\n{title}\n{'='*72}")
        for p in walk(data.get("panels", [])):
            if p.get("type") in ("row", "text"):
                continue
            ptitle = p.get("title", "?")[:55]
            for i, t in enumerate(p.get("targets") or []):
                sql, expr = t.get("rawSql"), t.get("expr")
                if sql:
                    result, err = q_postgres(sql, t.get("format", "table"))
                    src = "SQL"
                elif expr:
                    result, err = q_prom(expr)
                    src = "PromQL"
                else: continue
                if err:
                    print(f"  ❌ {ptitle:55s} [{src}] {err}")
                elif (isinstance(result, tuple) and not result[1]) or (isinstance(result, list) and not result):
                    print(f"  ⚠️  {ptitle:55s} [{src}] empty")
                else:
                    print(f"  ✅ {ptitle:55s} [{src}] {fmt_sample(result)}")
                break  # only first target per panel


if __name__ == "__main__":
    main()
