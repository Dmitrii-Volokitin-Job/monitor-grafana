# Screenshot Acceptance Criteria

Source-of-truth for every screenshot in this directory. A screenshot is
ACCEPTED only if **every panel below shows real data**, **values are
internally consistent across panels of the same dashboard**, and **no
test-artifact rows** (e.g. `test-httpbin-*`, `system_group=TEST_LAB`) are
visible. Any failure on any of these three axes is a REJECT and must be
re-shot after fixing the underlying cause.

## Global rules (apply to every dashboard)

### Rendering
- **Time range**: dashboard default (typically last 7 d). Do not override unless the panel's own default differs.
- **Variables**: keep at default (usually `system_group=All`, `alert_level=All`, `DS_PROMETHEUS=Prometheus`).
- **Browser**: 1920×1080 viewport-equivalent; capture full page (use the `grafana-image-renderer` plugin via `/render/d/<uid>/<slug>?width=1920&height=2400` — headless-Chrome `fullPage: true` does NOT render lazy panels in Grafana 11+, this is a known limitation).
- **No partial-load states** — wait until every panel has rendered (no spinning loaders, no "Loading…" overlay).
- **Login**: every dashboard requires Grafana admin/admin so the iframe panels render too.

### Visual consistency across dashboards (NEW)
- **Font sizes** for the same element class must match across all 6 dashboards. Concretely:
  - Stat-tile value text size: same across `System Status`, `Demo Lab A`, `Demo Lab B`, all SSL overview stat tiles, all Uptime gauges
  - Stat-tile title size: same across all stat panels
  - Table header / row text size: same across `All Monitored Systems`, SSL detail tables, Active Alerts table, Email Log table, Monitored Systems Postgres table
  - Time-axis labels and legend text: same size across all timeseries panels
- Stat-tile `textMode` MUST be `"value"` (not `"value_and_name"`) unless a panel deliberately needs the series name shown. The `value_and_name` mode prints the regex source like `.*` when the field selector is a regex with no `legendFormat` — that artifact ships in screenshots and looks broken.
- Stat-tile `reduceOptions.fields` MUST be empty string `""` (all numeric fields) unless a specific column is needed. The regex form `"/^(?!Time).*$/"` triggers the `.*` leak above.
- Table panels MUST set `footer.show: false` UNLESS the panel explicitly labels what the footer aggregates. An unlabeled "30" floating below a table is meaningless to a reader.
- HTML iframe panels MUST NOT embed `http://localhost:<port>/…` URLs because the renderer container's localhost is itself, not the host. Use a markdown link card instead — or, if the iframe is critical, document the working URL (`monitor-exporter:9119` in the docker network).

### Forbidden in any screenshot
- **"No data"** or **"N/A"** placeholders on any panel.
- **Test-artifact rows** in any table — `system_id` starting with `test-`, `system_group=TEST_LAB`, `display_name` starting with "Test ", or any auto-generated `test-*` rows from the live test suite.
- **Internal-only hostnames** (e.g. raw `monitor-exporter:9116` is OK as a `url` field when the row is a non-blackbox probe, but `10.0.0.x` / `192.168.x.x` / `172.16-31.x.x` placeholders must be gone — only RFC 5737 `192.0.2.x` is acceptable as a documentation IP).
- **Personal data** — names, internal emails, real ticket IDs, internal Slack channels.
- **Stale "Test mode" warnings** about email redirection (must be the generic placeholder text per the v0.0.1 cleanup).

### Cross-panel value consistency (NEW — critical)
Within a single dashboard, panels that count the same thing MUST agree:

| If panel A shows … | … panel B MUST show |
|---|---|
| `System Status: Down=3` | The table below should list 3 rows with `Status=DOWN` |
| `SSL Expired: 2` | The "Cert Expiring/Expired" table should list 2 rows with negative days_left, and the bargauge should show 2 bars with red |
| `Total Certificates: 4` | The bargauge should display 4 bars; the "All SSL Certificates" table should list 4 rows |
| `7d Uptime: 94.03%` | Hourly Uptime Trend should oscillate around 94%; Bottom-10 table's BEST row should be ≥ 94% |
| Alert History panel shows "5 firing" | The "Current Alerts" panel must list the same 5 alert rules (or a subset filtered by variable) |
| Email Log table shows "5 rows" | Email Audit Trail in Historical Data dashboard must show the same 5 rows |

Cross-dashboard consistency:
- `monitored_system` row count in Service Configuration table = unique system_id count in System Health Overview "All Monitored Systems" table.
- A system that's UP in System Health Overview's table must NOT appear as DOWN in the same time-range in Uptime Statistics "Bottom 10".

If counts don't reconcile: the panel queries are out of sync (filter-variable bug, wrong job label, etc.). FIX the dashboard JSON, don't just re-shoot.

## Per-dashboard acceptance criteria

### 1. `01-system-health-overview.png` — System Health Overview (`monitor-health-overview`)

12 panels. Screenshot must show:

| Row | Panel | Acceptable content | Cross-check |
|---|---|---|---|
| Overview | System Status (stat) | Health %, Total, Healthy, Down — all integers | Healthy + Down = Total |
| SSL Certificates | Next Cert Expiry (days) | Single integer/decimal | matches Earliest Expiry Date converted to days-from-now |
| SSL Certificates | Certs Valid | Integer ≥ 1 | Valid + Expiring + Expired = Total Certificates |
| SSL Certificates | Certs Expiring | Integer ≥ 0 | (same) |
| SSL Certificates | Certs Expired | Integer ≥ 0 | (same) |
| SSL Certificates | Top-5 soonest (bargauge) | ≥ 2 bars | count ≤ Total Certificates |
| All Systems | All Monitored Systems (table) | ≥ 10 rows, status icons, no `test-*` rows | matches Total in Service Configuration table |
| Trends | Uptime Trend by Group (timeseries) | ≥ 2 colored lines, non-zero | per-group avg matches Demo Lab A/B stat tiles |
| Trends | Response Time Trend (timeseries) | ≥ 2 lines, non-zero values | matches "Avg Response" in Bottom-10 table |
| Health Check Logs | Recent Health Check Logs (table) | ≥ 10 rows, real timestamps, status | system_ids appear in monitored_system |
| Per-lab | Demo Lab A — Primary (stat) | Numeric % | = avg(probe_success) for `system_group=demo-lab-a` |
| Per-lab | Demo Lab B — Secondary (stat) | Numeric % | = avg(probe_success) for `system_group=demo-lab-b` |

### 2. `02-ssl-certificates.png` — SSL Certificate Status (`monitor-ssl-certs`)

11 panels. Screenshot must show:

| Row | Panel | Acceptable content | Cross-check |
|---|---|---|---|
| Overview | Total Certificates | Integer ≥ 2 | = Valid + Expiring + Expired |
| Overview | Valid >30d | Integer ≥ 1 | (component of Total) |
| Overview | Expiring <30d | Integer ≥ 0 | (component of Total) |
| Overview | Expired | Integer ≥ 0 (expect ≥ 1 from badssl) | (component of Total) |
| Overview | Next Expiry (days) | Single value, may be negative if expired badssl present | = min(days_left) in Cert Expiring table |
| Overview | Earliest Expiry Date | Real ISO date | matches the system with min days_left |
| Requiring Attention | Cert Expiring/Expired (table) | ≥ 1 row (badssl negatives) | row count = Expiring + Expired counters |
| Days Until Expiry | bargauge | ≥ 4 bars (one per probed cert) | bar count = Total Certificates |
| Timeline | Cert Countdown (timeseries) | ≥ 1 line per cert; flat is OK | line count = Total Certificates |
| TLS Details | TLS Version & Probe Status (table) | ≥ 2 rows showing TLS version | rows ≤ Total Certificates |
| Full Details | All SSL Certificates (table) | ≥ 2 rows; cols: instance, days, status | row count = Total Certificates |

### 3. `03-alert-history.png` — Alert History & Email Log (`monitor-alert-history`)

3 panels. Screenshot must show:

| Panel | Acceptable content | Cross-check |
|---|---|---|
| Current Alerts (alertlist) | Either "No active alerts" OR ≥ 1 firing alert row | sum(firing+pending) ≤ count in Recent Alert History |
| Recent Alert History (alertlist) | ≥ 1 state-change entry | every alertname here must exist as a configured rule |
| Email Log (table) | ≥ 3 rows with sent_timestamp, subject, status | every row's `related_system_id` must exist in monitored_system; matches Email Audit Trail in Historical Data |

### 4. `04-historical-data.png` — Historical Data (Postgres) (`monitor-historical`)

6 panels. Screenshot must show:

| Row | Panel | Acceptable content | Cross-check |
|---|---|---|---|
| Health Check History | Health Check Status Over Time (timeseries) | ≥ 2 stepped lines, state changes visible | series names match systems in System Health Overview table |
| Health Check History | Response Time History (timeseries) | ≥ 2 lines with fluctuations | values match Recent Health Check Logs table's `response_time_ms` column |
| Historical Alerts | Active Alerts (table) | ≥ 1 row OR empty-state | row count matches alert_state.current_status IN (DOWN, WARNING, CRITICAL) |
| Historical Alerts | Current Alert Duration by Group (table) | ≥ 1 row per affected group | sum(alert_count) = total Active Alerts row count |
| Email Audit | Email Audit Trail (table) | ≥ 3 rows | identical row count to Alert History dashboard's Email Log |
| Maintenance | Upcoming & Active Maintenance Windows (table) | ≥ 1 row | row count = SELECT COUNT(*) FROM maintenance_window |

### 5. `05-uptime-statistics.png` — Uptime & Performance Statistics (`monitor-uptime-stats`)

6 panels. Screenshot must show:

| Row | Panel | Acceptable content | Cross-check |
|---|---|---|---|
| Uptime Percentages | 24h Uptime (gauge) | Numeric 0–100 | derived from health_check_history last 24h |
| Uptime Percentages | 7d Uptime (gauge) | Numeric 0–100 | 7d ≤ 24h tends to NOT hold (rolling windows), but both should be in 60-100% range with current data |
| Uptime Percentages | 30d Uptime (gauge) | Numeric 0–100 | (same) |
| Uptime by Group | Hourly Uptime Trend (timeseries) | ≥ 2 stepped lines | per-group mean matches Demo Lab A/B stat tiles |
| Worst Performing | Bottom 10 Systems by Uptime 7d (table) | ≥ 5 rows | uptime % matches 7d gauge avg for that group |
| Daily Trend | Daily Uptime Trend (timeseries) | ≥ 2 stepped lines, ≥ 7 days | 7-day average matches 7d Uptime gauge |

### 6. `06-service-configuration.png` — Service Configuration (`monitor-service-config`)

3 panels (header text + table + iframe). Screenshot must show:

| Panel | Acceptable content | Cross-check |
|---|---|---|
| (text header) | Rendered markdown title | — |
| Monitored Systems table | ≥ 20 rows showing every seed system. Columns: DB ID, System ID, Display Name, Type, URL, Group, Enabled, Last edited | row count = unique system_id count in System Health Overview's "All Monitored Systems" table; NO `test-*` rows |
| (admin UI iframe + text footer) | Either rendered admin UI OR Grafana login redirect (cross-origin cookie limitation is acceptable for the screenshot — the panel itself works for logged-in users) | — |

## How to verify a screenshot (3-pass procedure)

For each PNG file:

### Pass 1 — every panel renders
- No "No data", no "N/A", no loading spinners.
- Every panel listed in the per-dashboard table is visible.

### Pass 2 — internal logic consistency
- Apply the cross-check column for every row.
- If any cross-check fails: the dashboard JSON has a query bug. FIX it before re-shooting.

### Pass 3 — artifact hunt
- Search the rendered text for:
  - `test-` prefix in any cell
  - `TEST_LAB` in any group cell
  - Real internal IPs (`10.x`, `172.16-31.x`, `192.168.x`)
  - Real personal names (maintainer's first or last name, anyone on the team)
  - Stale "TEST MODE" / "redirect to" banners
  - Email addresses that aren't `*@example.com` / `alerts@example.com`
- Any hit → fix the seed/DB/template → re-shoot.

## How to capture (the working recipe)

1. **Enable image-renderer** in docker-compose:
   ```yaml
   environment:
     - GF_INSTALL_PLUGINS=grafana-image-renderer
   ```
   Restart Grafana, wait for plugin install (~60s on first download).

2. **Hit the render endpoint per dashboard:**
   ```bash
   for d in monitor-health-overview monitor-ssl-certs monitor-alert-history \
            monitor-historical monitor-uptime-stats monitor-service-config; do
     curl -sf -u admin:admin -o "/tmp/${d}.png" \
       "http://localhost:3030/render/d/${d}/x?width=1920&height=2400&tz=Europe%2FVienna&from=now-7d&to=now"
   done
   ```

3. **Run the 3-pass verification** above on each PNG.

4. **If any pass fails** — fix the underlying cause (seed data, query, panel config), then redo step 2 for the affected dashboard.

## File naming convention

```
docs/screenshots/0N-<dashboard-slug>.png
```

| File | Dashboard UID | Slug |
|---|---|---|
| `01-system-health-overview.png` | `monitor-health-overview` | `system-health-overview` |
| `02-ssl-certificates.png` | `monitor-ssl-certs` | `ssl-certificate-status` |
| `03-alert-history.png` | `monitor-alert-history` | `alert-history-and-email-log` |
| `04-historical-data.png` | `monitor-historical` | `historical-data-postgres` |
| `05-uptime-statistics.png` | `monitor-uptime-stats` | `uptime-and-performance-statistics` |
| `06-service-configuration.png` | `monitor-service-config` | `service-configuration` |

Iteration-suffix files from past sessions (`-after-fix`, `-with-data`, `-final`, etc.) must be deleted; only the canonical `0N-<slug>.png` survives.

## Why this matters

Public docs and the README link these screenshots. If they show `test-httpbin-1780179106` (an artifact from a live-test fixture that wasn't cleaned up), or report "Total=10 but Down=12" (an inconsistency that signals a real query bug), or contain any internal maintainer name — that ships to GitHub and tells users "this project's data plumbing is broken / has been used internally." The 3-pass procedure catches all three classes in one read-through.
