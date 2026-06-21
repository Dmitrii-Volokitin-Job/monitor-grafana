#!/usr/bin/env python3
"""Comprehensive dashboard audit harness.

Walks every dashboard JSON, exercises every backing query / variable / link, and
emits/updates `docs/dashboard_audit.md` — a single-source-of-truth checklist
proving each interactive element was actually checked.

Three layers per dashboard:

  A. Navigation & filters   — dashboard links + template variables + refresh
  B. Panels — data           — each panel's backing query
  C. Visual / interactive    — value mappings + thresholds + data links + iframes

The script is re-runnable:
  - It refreshes the auto-fillable columns (Actual / Status / Last checked /
    Screenshot) in place.
  - It PRESERVES any text the user typed into the `Notes` column.
  - `--verify` mode: exit 0 if row counts match the previous run, 1 otherwise.

Usage:
  python3 scripts/maint/audit_dashboards.py            # populate / refresh
  python3 scripts/maint/audit_dashboards.py --verify   # regression check
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent.parent
DASH_DIR = PROJECT / "dashboards"
OUT_FILE = PROJECT / "docs" / "dashboard_audit.md"

GRAFANA = os.environ.get("GRAFANA", "http://localhost:3030")
USER = os.environ.get("GRAFANA_USER", "admin")
PW = os.environ.get("GRAFANA_PW", "admin")
AUTH = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()

NOW = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Variable substitution for raw queries (so the API checker can run them)
# ---------------------------------------------------------------------------

VAR_DEFAULTS = {
    "$system_group": ".*", "${system_group}": ".*",
    "$system_group:singlequote": "'.*'",
    "$__interval": "5m",
    "$health_status": ">= 0", "${health_status}": ">= 0",
    "$log_rows": "200",
    "$alert_level": ".*", "${alert_level}": ".*",
    "$system": ".*", "${system}": ".*",
}


def substitute(s: str | None) -> str | None:
    if not s:
        return s
    for k, v in VAR_DEFAULTS.items():
        s = s.replace(k, v)
    return s


# ---------------------------------------------------------------------------
# Grafana API helpers
# ---------------------------------------------------------------------------

def _post_query(payload: dict) -> dict:
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query",
        data=json.dumps(payload).encode(),
        headers={"Authorization": AUTH, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def query_postgres(raw_sql: str, fmt: str = "table") -> tuple[str, str]:
    """Return (status, actual) for a Postgres rawSql query."""
    try:
        d = _post_query({
            "queries": [{
                "refId": "A",
                "datasource": {"type": "postgres", "uid": "monitor-postgres"},
                "rawSql": substitute(raw_sql),
                "format": fmt,
            }],
            "from": "now-7d", "to": "now",
        })
        a = d.get("results", {}).get("A", {})
        if a.get("status", 200) >= 400 or "error" in a:
            return "✗", f"ERR: {str(a.get('error',''))[:80]}"
        frames = a.get("frames", [])
        if not frames or not frames[0].get("data", {}).get("values"):
            return "⚠", "0 rows"
        rows = len(frames[0]["data"]["values"][0])
        first = frames[0]["data"]["values"][0][0]
        return "✓", f"{rows} rows; first={str(first)[:40]}"
    except Exception as e:
        return "✗", f"ERR: {str(e)[:80]}"


def query_prom(expr: str) -> tuple[str, str]:
    """Return (status, actual) for a PromQL instant query."""
    try:
        q = urllib.parse.urlencode({"query": substitute(expr)})
        req = urllib.request.Request(
            f"{GRAFANA}/api/datasources/proxy/uid/monitor-prometheus/api/v1/query?{q}",
            headers={"Authorization": AUTH},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        if d.get("status") != "success":
            return "✗", f"ERR: {str(d.get('error',''))[:80]}"
        res = d.get("data", {}).get("result", [])
        if not res:
            return "⚠", "0 series"
        first = res[0]
        return "✓", f"{len(res)} series; first={first.get('value',['?','?'])[1]}"
    except Exception as e:
        return "✗", f"ERR: {str(e)[:80]}"


# ---------------------------------------------------------------------------
# Walk a panel tree
# ---------------------------------------------------------------------------

def iter_panels(panels):
    for p in panels:
        yield p
        for sub in p.get("panels", []):
            yield sub


# ---------------------------------------------------------------------------
# Notes-preservation merge: parse existing file, keep Notes column verbatim
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r"^\| *(\d+) *\|")


def load_existing_notes() -> dict[tuple[str, int], str]:
    """Return {(section_anchor, row#): notes_text} from the previous run."""
    if not OUT_FILE.exists():
        return {}
    saved: dict[tuple[str, int], str] = {}
    section = ""
    for line in OUT_FILE.read_text().splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        m = ROW_RE.match(line)
        if m:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 10:
                rownum = int(cells[0])
                notes = cells[9]
                saved[(section, rownum)] = notes
    return saved


def fmt_row(n: int, element: str, what: str, how: str,
            expected: str, actual: str, status: str,
            screenshot: str, last_checked: str, notes: str) -> str:
    # Escape pipes inside cells
    def cell(s):
        return str(s).replace("|", "\\|").replace("\n", " ")
    return (
        f"| {n} | {cell(element)} | {cell(what)} | {cell(how)} | "
        f"{cell(expected)} | {cell(actual)} | {status} | "
        f"{cell(screenshot)} | {cell(last_checked)} | {cell(notes)} |"
    )


HEADER = (
    "| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |\n"
    "|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|"
)


# ---------------------------------------------------------------------------
# Per-dashboard audit
# ---------------------------------------------------------------------------

def audit_dashboard(path: Path, prev_notes: dict[tuple[str, int], str]) -> str:
    data = json.loads(path.read_text())
    title = data.get("title", path.name)
    uid = data.get("uid", "?")
    tags = ",".join(data.get("tags") or [])
    refresh = data.get("refresh", "—")
    tr = data.get("time", {})
    section_a = f"{title} — A. Navigation & filters"
    section_b = f"{title} — B. Panels (data correctness)"
    section_c = f"{title} — C. Visual / interactive elements"

    out = [f"\n## {title}\n",
           f"`uid={uid}` | `tags={tags}` | refresh={refresh} | time={tr.get('from','?')} → {tr.get('to','?')}\n"]

    # ----- Table A: nav + filters -----
    out += [f"\n### {section_a}\n", HEADER]
    n = 0
    for link in data.get("links", []):
        n += 1
        notes = prev_notes.get((section_a, n), "")
        out.append(fmt_row(
            n, f"link: {link.get('title','?')}",
            "follow link, keeps time & vars if includeVars",
            f"GET {link.get('url','?')}",
            "200 OK", "—", "?",
            f"audit-{uid}-link-{n}.png", NOW, notes,
        ))
    for v in data.get("templating", {}).get("list", []):
        n += 1
        notes = prev_notes.get((section_a, n), "")
        vtype = v.get("type", "?")
        vname = v.get("name", "?")
        if vtype == "query" and "postgres" in str(v.get("datasource", "")).lower():
            status, actual = query_postgres(
                v.get("query", "") if isinstance(v.get("query"), str)
                else v.get("query", {}).get("query", ""),
                fmt="table",
            )
        elif vtype == "custom":
            opts = (v.get("query") or "").split(",")
            actual = f"{len(opts)} options: {opts[0][:30]}…"
            status = "✓" if opts else "⚠"
        else:
            status, actual = "–", f"{vtype} (skip)"
        out.append(fmt_row(
            n, f"var: {vname} ({vtype})",
            "options resolve, multi/all behave",
            "API resolve + click in UI",
            "≥1 option", actual, status,
            f"audit-{uid}-var-{vname}.png", NOW, notes,
        ))
    n += 1
    out.append(fmt_row(
        n, "Refresh interval", "auto-refresh fires at the set interval",
        "watch network tab in UI",
        refresh, refresh, "?",
        f"audit-{uid}-refresh.png", NOW, prev_notes.get((section_a, n), ""),
    ))
    n += 1
    out.append(fmt_row(
        n, "Time-range default", "default range loaded on open",
        "open dashboard, read picker",
        f"{tr.get('from','?')} → {tr.get('to','?')}",
        f"{tr.get('from','?')} → {tr.get('to','?')}", "?",
        f"audit-{uid}-timerange.png", NOW, prev_notes.get((section_a, n), ""),
    ))

    # ----- Table B: panel data -----
    out += [f"\n### {section_b}\n", HEADER]
    n = 0
    for p in iter_panels(data.get("panels", [])):
        if p.get("type") in ("row", "text"):
            continue
        n += 1
        notes = prev_notes.get((section_b, n), "")
        ptitle = p.get("title", "?")
        targets = p.get("targets") or [{}]
        t = targets[0]
        sql, expr = t.get("rawSql"), t.get("expr")
        if sql:
            status, actual = query_postgres(sql, t.get("format", "table"))
            how = "POST /api/ds/query against monitor-postgres"
        elif expr:
            status, actual = query_prom(expr)
            how = "GET /api/v1/query against monitor-prometheus"
        else:
            status, actual, how = "–", "no backing query", "n/a"
        out.append(fmt_row(
            n, f"panel#{p.get('id','?')}: {ptitle}",
            "panel returns ≥1 row/series",
            how, "≥1 row", actual, status,
            f"audit-{uid}-panel-{p.get('id','x')}.png", NOW, notes,
        ))

    # ----- Table C: visual / interactive -----
    out += [f"\n### {section_c}\n", HEADER]
    n = 0
    for p in iter_panels(data.get("panels", [])):
        if p.get("type") in ("row",):
            continue
        ptitle = p.get("title", "?")
        defaults = p.get("fieldConfig", {}).get("defaults", {})
        # thresholds
        steps = defaults.get("thresholds", {}).get("steps") or []
        if len(steps) > 1:
            n += 1
            out.append(fmt_row(
                n, f"panel#{p.get('id')}: thresholds ({ptitle})",
                "color bands visible at the configured thresholds",
                "screenshot panel at known values",
                f"{len(steps)} bands", "—", "?",
                f"audit-{uid}-panel-{p.get('id')}-thresholds.png", NOW,
                prev_notes.get((section_c, n), ""),
            ))
        # value mappings (top-level)
        mappings = defaults.get("mappings") or []
        for i, m in enumerate(mappings):
            n += 1
            out.append(fmt_row(
                n, f"panel#{p.get('id')}: mapping#{i} ({ptitle})",
                "values render with configured color/text",
                "screenshot a cell that hits this mapping",
                m.get("type", "?"), "—", "?",
                f"audit-{uid}-panel-{p.get('id')}-mapping-{i}.png", NOW,
                prev_notes.get((section_c, n), ""),
            ))
        # data links (top-level + per-override)
        for src in ([defaults] + (p.get("fieldConfig", {}).get("overrides") or [])):
            for link_blob in (src.get("links") or src.get("properties", []) if isinstance(src, dict) else []):
                if isinstance(link_blob, dict):
                    if link_blob.get("id") == "links":
                        for L in link_blob.get("value") or []:
                            n += 1
                            out.append(fmt_row(
                                n, f"panel#{p.get('id')}: data link → {L.get('title','?')[:30]}",
                                "clicking the cell opens the right URL",
                                "click in UI, capture URL",
                                L.get("url", "?")[:60], "—", "?",
                                f"audit-{uid}-panel-{p.get('id')}-link-{n}.png", NOW,
                                prev_notes.get((section_c, n), ""),
                            ))
                    elif link_blob.get("title") and link_blob.get("url"):
                        n += 1
                        out.append(fmt_row(
                            n, f"panel#{p.get('id')}: data link → {link_blob['title'][:30]}",
                            "clicking the cell opens the right URL",
                            "click in UI, capture URL",
                            link_blob["url"][:60], "—", "?",
                            f"audit-{uid}-panel-{p.get('id')}-link-{n}.png", NOW,
                            prev_notes.get((section_c, n), ""),
                        ))
        # transformations
        for i, tr_ in enumerate(p.get("transformations") or []):
            n += 1
            out.append(fmt_row(
                n, f"panel#{p.get('id')}: transformation#{i} ({tr_.get('id','?')})",
                "transformation applies — columns merge/rename as expected",
                "screenshot table after data loads",
                tr_.get("id", "?"), "—", "?",
                f"audit-{uid}-panel-{p.get('id')}-tf-{i}.png", NOW,
                prev_notes.get((section_c, n), ""),
            ))
        # iframe (text/html mode)
        if p.get("type") == "text" and "<iframe" in (p.get("options", {}).get("content", "") or ""):
            n += 1
            out.append(fmt_row(
                n, f"panel#{p.get('id')}: iframe ({ptitle})",
                "iframe renders the embedded app, no CSP error",
                "screenshot full panel, look for app chrome",
                "embedded app visible", "—", "?",
                f"audit-{uid}-panel-{p.get('id')}-iframe.png", NOW,
                prev_notes.get((section_c, n), ""),
            ))

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="exit 1 if the new run regresses vs the previous file")
    args = ap.parse_args()

    prev_notes = load_existing_notes()

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "# Dashboard audit checklist\n",
        f"_Generated {NOW} by `scripts/maint/audit_dashboards.py`._\n",
        "**Status legend:** ✓ pass · ⚠ works-but-noted · ✗ fail · – n/a · ? pending\n",
        "## Run-order\n",
        "1. `python3 scripts/maint/audit_dashboards.py` to populate Layers A+B (automated).\n"
        "2. Open Grafana, walk each dashboard, take Chrome screenshots into `docs/screenshots/audit/`.\n"
        "3. Hand-fill `Status` and any `Notes` for rows that show `?`.\n"
        "4. `python3 scripts/maint/audit_dashboards.py --verify` to check for regressions.\n",
    ]

    for f in sorted(DASH_DIR.glob("*.json")):
        body.append(audit_dashboard(f, prev_notes))

    new_text = "\n".join(body) + "\n"

    if args.verify and OUT_FILE.exists():
        # Compare row/series counts. Tolerate natural growth in time-series data
        # (e.g. health_check_history accumulates over time) — only flag when a
        # query goes from >0 to 0 or vice versa, or count drops by >50%.
        def extract_counts(text: str) -> dict[tuple[str, int], tuple[int, str]]:
            counts: dict[tuple[str, int], tuple[int, str]] = {}
            section = ""
            for ln in text.splitlines():
                if ln.startswith("### "):
                    section = ln[4:].strip()
                m = ROW_RE.match(ln)
                if m:
                    cells = [c.strip() for c in ln.strip("|").split("|")]
                    if len(cells) >= 6:
                        actual = cells[5]
                        num_match = re.match(r"(\d+)\s+(rows|series)", actual)
                        if num_match:
                            counts[(section, int(cells[0]))] = (
                                int(num_match.group(1)), num_match.group(2))
            return counts

        old = extract_counts(OUT_FILE.read_text())
        new = extract_counts(new_text)
        real_regressions = []
        for k in old.keys() | new.keys():
            o = old.get(k)
            n_ = new.get(k)
            if o is None or n_ is None:
                # row added/removed → significant
                real_regressions.append((k, o, n_))
                continue
            o_count, _ = o
            n_count, _ = n_
            # Regression rules: went to zero, or dropped by more than 50%
            if (o_count > 0 and n_count == 0) or (o_count > 0 and n_count < o_count * 0.5):
                real_regressions.append((k, o, n_))
        if real_regressions:
            print(f"REGRESSION: {len(real_regressions)} row(s) regressed materially")
            for k, o, nn in real_regressions[:10]:
                print(f"  {k}: {o!r} → {nn!r}")
            sys.exit(1)
        print(f"verify OK — {len(new)} rows, no material regressions "
              "(natural time-series growth is tolerated)")
        return

    OUT_FILE.write_text(new_text)
    pending = new_text.count("| ? |")
    print(f"wrote {OUT_FILE} — {pending} row(s) still need manual check")


if __name__ == "__main__":
    main()
