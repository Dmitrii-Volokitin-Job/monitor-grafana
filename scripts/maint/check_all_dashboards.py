#!/usr/bin/env python3
"""Walk every dashboard panel and exercise its query against the running stack.

For each panel target:
  - rawSql (Postgres targets) → POST to /api/ds/query, expect non-error response
  - expr (Prometheus targets) → GET /api/datasources/proxy/<uid>/api/v1/query, expect data
Prints a per-dashboard summary: panels OK / WARN / ERROR.
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import base64
from pathlib import Path

GRAFANA = os.environ.get("GRAFANA", "http://localhost:3030")
USER = os.environ.get("GRAFANA_USER", "admin")
PW = os.environ.get("GRAFANA_PW", "admin")
AUTH = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()
DASH_DIR = Path(__file__).resolve().parent.parent.parent / "dashboards"


def substitute_vars(s):
    """Replace common dashboard $vars with sensible defaults for testing."""
    if not s:
        return s
    repl = {
        "$system_group": ".*", "${system_group}": ".*",
        "$system_group:singlequote": "'.*'",
        "$__interval": "5m",
        "$lab_group": ".*", "${lab_group}": ".*",
        "$node": ".*", "${node}": ".*",
        "$db": "monitor-postgres", "${db}": "monitor-postgres",
        "$datasource": "monitor-postgres", "${datasource}": "monitor-postgres",
        "$project_key": "customer-portal", "${project_key}": "customer-portal",
        "$environment": "base", "${environment}": "base",
        "$branch": "All", "${branch}": "All",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def query_postgres(raw_sql, fmt="table"):
    """POST a rawSql to /api/ds/query for monitor-postgres."""
    body = json.dumps({
        "queries": [{
            "refId": "A",
            "datasource": {"type": "postgres", "uid": "monitor-postgres"},
            "rawSql": substitute_vars(raw_sql),
            "format": fmt,
        }],
        "from": "now-7d", "to": "now",
    }).encode()
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query",
        data=body,
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        a = d.get("results", {}).get("A", {})
        if a.get("status", 200) >= 400 or "error" in a:
            return ("ERROR", a.get("error", "unknown")[:120])
        frames = a.get("frames", [])
        if not frames:
            return ("WARN", "no frames")
        n_rows = sum(len(f.get("data", {}).get("values", [[]])[0] or []) for f in frames)
        if n_rows == 0:
            return ("WARN", "0 rows")
        return ("OK", f"{n_rows} rows")
    except Exception as e:
        return ("ERROR", str(e)[:120])


def query_prom(expr):
    """GET /api/datasources/proxy/<prom-uid>/api/v1/query?query=…"""
    q = urllib.parse.urlencode({"query": substitute_vars(expr)})
    req = urllib.request.Request(
        f"{GRAFANA}/api/datasources/proxy/uid/monitor-prometheus/api/v1/query?{q}",
        headers={"Authorization": AUTH},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        if d.get("status") != "success":
            return ("ERROR", d.get("error", "unknown")[:120])
        res = d.get("data", {}).get("result", [])
        if not res:
            return ("WARN", "0 series")
        return ("OK", f"{len(res)} series")
    except Exception as e:
        return ("ERROR", str(e)[:120])


def walk(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from walk(x)
    elif isinstance(obj, dict):
        if "type" in obj and "targets" in obj:
            yield obj
        for v in obj.values():
            yield from walk(v)


def check_dashboard(path):
    data = json.loads(path.read_text())
    title = data.get("title", path.name)
    counts = {"OK": 0, "WARN": 0, "ERROR": 0, "SKIP": 0}
    issues = []
    for panel in walk(data.get("panels", [])):
        if panel.get("type") in ("row", "text"):
            continue
        for t in panel.get("targets") or []:
            sql = t.get("rawSql")
            expr = t.get("expr")
            if sql:
                status, detail = query_postgres(sql, t.get("format", "table"))
            elif expr:
                status, detail = query_prom(expr)
            else:
                continue
            counts[status] += 1
            if status in ("ERROR", "WARN"):
                issues.append((panel.get("title", "?"), status, detail[:80]))
    return title, counts, issues


def main():
    files = sorted(DASH_DIR.glob("*.json"))
    print(f"\n{'Dashboard':40s} {'OK':>4} {'WARN':>5} {'ERR':>4}")
    print("-" * 60)
    total = {"OK": 0, "WARN": 0, "ERROR": 0}
    all_issues = []
    for f in files:
        title, counts, issues = check_dashboard(f)
        print(f"{title[:39]:40s} {counts['OK']:>4} {counts['WARN']:>5} {counts['ERROR']:>4}")
        for k in total:
            total[k] += counts[k]
        if issues:
            all_issues.append((title, issues))
    print("-" * 60)
    print(f"{'TOTAL':40s} {total['OK']:>4} {total['WARN']:>5} {total['ERROR']:>4}")

    if all_issues:
        print("\n--- Detailed issues ---")
        for title, issues in all_issues:
            print(f"\n[{title}]")
            for p, s, d in issues:
                print(f"  {s:5s} {p[:50]:50s} {d}")


if __name__ == "__main__":
    main()
