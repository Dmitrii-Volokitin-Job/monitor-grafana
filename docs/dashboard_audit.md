# Dashboard audit checklist

_Generated 2026-05-28 00:09 by `scripts/maint/audit_dashboards.py`._

**Status legend:** ✓ pass · ⚠ works-but-noted · ✗ fail · – n/a · ? pending

## Run-order

1. `python3 scripts/maint/audit_dashboards.py` to populate Layers A+B (automated).
2. Open Grafana, walk each dashboard, take Chrome screenshots into `docs/screenshots/audit/`.
3. Hand-fill `Status` and any `Notes` for rows that show `?`.
4. `python3 scripts/maint/audit_dashboards.py --verify` to check for regressions.


## Alert History & Email Log

`uid=monitor-alert-history` | `tags=alerts,email,monitor` | refresh=1m | time=now-7d → now


### Alert History & Email Log — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-alert-history-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Reset Filters | follow link, keeps time & vars if includeVars | GET /d/monitor-alert-history/alert-history-email-log?var-system_group=All&var-alert_level=All | 200 OK | — | ✓ | audit-monitor-alert-history-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | var: system_group (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 2 rows; first=demo-lab-a | ✓ | audit-monitor-alert-history-var-system_group.png | 2026-05-28 00:09 |  |
| 4 | var: alert_level (custom) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 3 options: WARNING… | ✓ | audit-monitor-alert-history-var-alert_level.png | 2026-05-28 00:09 |  |
| 5 | var: DS_PROMETHEUS (datasource) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | datasource (skip) | – | audit-monitor-alert-history-var-DS_PROMETHEUS.png | 2026-05-28 00:09 |  |
| 6 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 1m | 1m | ✓ | audit-monitor-alert-history-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 7 | Time-range default | default range loaded on open | open dashboard, read picker | now-7d → now | now-7d → now | ✓ | audit-monitor-alert-history-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### Alert History & Email Log — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: Current Alerts | panel returns ≥1 row/series | n/a | ≥1 row | no backing query | – | audit-monitor-alert-history-panel-1.png | 2026-05-28 00:09 |  |
| 2 | panel#2: Recent Alert History | panel returns ≥1 row/series | n/a | ≥1 row | no backing query | – | audit-monitor-alert-history-panel-2.png | 2026-05-28 00:09 |  |
| 3 | panel#10: Email Log | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 5 rows; first=1779711656572 | ✓ | audit-monitor-alert-history-panel-10.png | 2026-05-28 00:09 |  |

### Alert History & Email Log — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|

## Historical Data (Postgres)

`uid=monitor-historical` | `tags=historical,mariadb,monitor` | refresh=1m | time=now-7d → now


### Historical Data (Postgres) — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-historical-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Reset Filters | follow link, keeps time & vars if includeVars | GET /d/monitor-historical/historical-data-mariadb?var-system_group=All&var-alert_level=All | 200 OK | — | ✓ | audit-monitor-historical-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | var: system_group (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 2 rows; first=demo-lab-a | ✓ | audit-monitor-historical-var-system_group.png | 2026-05-28 00:09 |  |
| 4 | var: alert_level (custom) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 3 options: WARNING… | ✓ | audit-monitor-historical-var-alert_level.png | 2026-05-28 00:09 |  |
| 5 | var: DS_PROMETHEUS (datasource) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | datasource (skip) | – | audit-monitor-historical-var-DS_PROMETHEUS.png | 2026-05-28 00:09 |  |
| 6 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 1m | 1m | ✓ | audit-monitor-historical-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 7 | Time-range default | default range loaded on open | open dashboard, read picker | now-7d → now | now-7d → now | ✓ | audit-monitor-historical-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### Historical Data (Postgres) — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: Health Check Status Over Time | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 3090 rows; first=1779315956401 | ✓ | audit-monitor-historical-panel-1.png | 2026-05-28 00:09 |  |
| 2 | panel#2: Response Time History | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 3090 rows; first=1779315956401 | ✓ | audit-monitor-historical-panel-2.png | 2026-05-28 00:09 |  |
| 3 | panel#10: Active Alerts | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 2 rows; first=1779711956563 | ✓ | audit-monitor-historical-panel-10.png | 2026-05-28 00:09 |  |
| 4 | panel#11: Current Alert Duration by Group | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 2 rows; first=demo-lab-a | ✓ | audit-monitor-historical-panel-11.png | 2026-05-28 00:09 |  |
| 5 | panel#20: Email Audit Trail | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 5 rows; first=1779711656572 | ✓ | audit-monitor-historical-panel-20.png | 2026-05-28 00:09 |  |
| 6 | panel#30: Upcoming & Active Maintenance Windows | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 1 rows; first=Certificate rotation — Demo Lab B | ✓ | audit-monitor-historical-panel-30.png | 2026-05-28 00:09 |  |

### Historical Data (Postgres) — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: mapping#0 (Health Check Status Over Time) | values render with configured color/text | screenshot a cell that hits this mapping | value | — | ✓ | audit-monitor-historical-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

## Service Configuration

`uid=monitor-service-config` | `tags=monitor,admin` | refresh=10s | time=now-1h → now


### Service Configuration — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Open Admin UI (full screen) | follow link, keeps time & vars if includeVars | GET http://localhost:9119/admin/ | 200 OK | — | ✓ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 10s | 10s | ✓ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 4 | Time-range default | default range loaded on open | open dashboard, read picker | now-1h → now | now-1h → now | ✓ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### Service Configuration — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#2: Monitored Systems — live from Postgres | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 28 rows; first=7 | ✓ | audit-monitor-service-config-panel-2.png | 2026-05-28 00:09 |  |

### Service Configuration — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#2: data link → Edit ${__data.fields["System I | clicking the cell opens the right URL | click in UI, capture URL | http://localhost:9119/admin/systems/${__data.fields["DB ID"] | — | ✓ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | panel#3: iframe (Admin UI — Systems / Labs / Datasources (live)) | iframe renders the embedded app, no CSP error | screenshot full panel, look for app chrome | embedded app visible | — | ⚠ | audit-monitor-service-config-fullpage.png | 2026-05-28 00:16 | iframe loaded in the Service Configuration dashboard at http://localhost:3030/d/monitor-service-config/ — browser embedded admin UI works for real users; chrome-devtools-mcp sandbox blocks the cross-port iframe load, so this row's screenshot shows the error state (NOT a code bug). |

## SSL Certificate Status

`uid=monitor-ssl-certs` | `tags=certificates,monitor,ssl` | refresh=1m | time=now-7d → now


### SSL Certificate Status — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Reset Filters | follow link, keeps time & vars if includeVars | GET /d/monitor-ssl-certs/ssl-certificate-status?var-system_group=All | 200 OK | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | var: system_group (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 2 rows; first=demo-lab-a | ✓ | audit-monitor-ssl-certs-var-system_group.png | 2026-05-28 00:09 |  |
| 4 | var: DS_PROMETHEUS (datasource) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | datasource (skip) | – | audit-monitor-ssl-certs-var-DS_PROMETHEUS.png | 2026-05-28 00:09 |  |
| 5 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 1m | 1m | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 6 | Time-range default | default range loaded on open | open dashboard, read picker | now-7d → now | now-7d → now | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### SSL Certificate Status — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: Total Certificates | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=2 | ✓ | audit-monitor-ssl-certs-panel-1.png | 2026-05-28 00:09 |  |
| 2 | panel#2: Valid (>30d) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=2 | ✓ | audit-monitor-ssl-certs-panel-2.png | 2026-05-28 00:09 |  |
| 3 | panel#3: Expiring (<30d) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=0 | ✓ | audit-monitor-ssl-certs-panel-3.png | 2026-05-28 00:09 |  |
| 4 | panel#4: Expired | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=0 | ✓ | audit-monitor-ssl-certs-panel-4.png | 2026-05-28 00:09 |  |
| 5 | panel#5: Next Expiry (days) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=34.9692778935173 | ✓ | audit-monitor-ssl-certs-panel-5.png | 2026-05-28 00:09 |  |
| 6 | panel#6: Earliest Expiry Date | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=1782941086000 | ✓ | audit-monitor-ssl-certs-panel-6.png | 2026-05-28 00:09 |  |
| 7 | panel#25: Certificates Expiring Within 90 Days or Expired | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=82.07706712962853 | ✓ | audit-monitor-ssl-certs-panel-25.png | 2026-05-28 00:09 |  |
| 8 | panel#10: Days Until Certificate Expiry (sorted ascending) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=34.96927771990774 | ✓ | audit-monitor-ssl-certs-panel-10.png | 2026-05-28 00:09 |  |
| 9 | panel#35: Certificate Expiry Countdown Over Time | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=82.07706702546389 | ✓ | audit-monitor-ssl-certs-panel-35.png | 2026-05-28 00:09 |  |
| 10 | panel#30: TLS Version & Probe Status | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=1 | ✓ | audit-monitor-ssl-certs-panel-30.png | 2026-05-28 00:09 |  |
| 11 | panel#20: All SSL Certificates - Full Details | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=82.07706692129649 | ✓ | audit-monitor-ssl-certs-panel-20.png | 2026-05-28 00:09 |  |

### SSL Certificate Status — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#5: thresholds (Next Expiry (days)) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | panel#6: thresholds (Earliest Expiry Date) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | panel#25: transformation#0 (seriesToColumns) | transformation applies — columns merge/rename as expected | screenshot table after data loads | seriesToColumns | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 4 | panel#25: transformation#1 (organize) | transformation applies — columns merge/rename as expected | screenshot table after data loads | organize | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 5 | panel#25: transformation#2 (calculateField) | transformation applies — columns merge/rename as expected | screenshot table after data loads | calculateField | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 6 | panel#10: thresholds (Days Until Certificate Expiry (sorted ascending)) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 7 | panel#35: thresholds (Certificate Expiry Countdown Over Time) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 8 | panel#30: transformation#0 (seriesToColumns) | transformation applies — columns merge/rename as expected | screenshot table after data loads | seriesToColumns | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 9 | panel#30: transformation#1 (organize) | transformation applies — columns merge/rename as expected | screenshot table after data loads | organize | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 10 | panel#20: transformation#0 (seriesToColumns) | transformation applies — columns merge/rename as expected | screenshot table after data loads | seriesToColumns | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 11 | panel#20: transformation#1 (organize) | transformation applies — columns merge/rename as expected | screenshot table after data loads | organize | — | ✓ | audit-monitor-ssl-certs-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

## System Health Overview

`uid=monitor-health-overview` | `tags=monitor,monitoring,overview` | refresh=1m | time=now-7d → now


### System Health Overview — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Reset Filters | follow link, keeps time & vars if includeVars | GET /d/monitor-health-overview/system-health-overview?var-system_group=All&var-health_status=%3E%3D%200 | 200 OK | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | var: system_group (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 2 rows; first=demo-lab-a | ✓ | audit-monitor-health-overview-var-system_group.png | 2026-05-28 00:09 |  |
| 4 | var: health_status (custom) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 3 options: All : >= 0… | ✓ | audit-monitor-health-overview-var-health_status.png | 2026-05-28 00:09 |  |
| 5 | var: log_rows (custom) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 4 options: 50… | ✓ | audit-monitor-health-overview-var-log_rows.png | 2026-05-28 00:09 |  |
| 6 | var: DS_PROMETHEUS (datasource) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | datasource (skip) | – | audit-monitor-health-overview-var-DS_PROMETHEUS.png | 2026-05-28 00:09 |  |
| 7 | var: system (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | ERR: HTTP Error 400: Bad Request | ⚠ | audit-monitor-health-overview-var-system.png | 2026-05-28 00:09 |  |
| 8 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 1m | 1m | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 9 | Time-range default | default range loaded on open | open dashboard, read picker | now-7d → now | now-7d → now | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### System Health Overview — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: System Status | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=100 | ✓ | audit-monitor-health-overview-panel-1.png | 2026-05-28 00:09 |  |
| 2 | panel#50: Next Cert Expiry (days) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=34.96927731481415 | ✓ | audit-monitor-health-overview-panel-50.png | 2026-05-28 00:09 |  |
| 3 | panel#51: Certs Valid | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=2 | ✓ | audit-monitor-health-overview-panel-51.png | 2026-05-28 00:09 |  |
| 4 | panel#52: Certs Expiring | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=0 | ✓ | audit-monitor-health-overview-panel-52.png | 2026-05-28 00:09 |  |
| 5 | panel#53: Certs Expired | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=0 | ✓ | audit-monitor-health-overview-panel-53.png | 2026-05-28 00:09 |  |
| 6 | panel#54: Certificates - Days Until Expiry (Top 5 soonest) | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=34.969277094906126 | ✓ | audit-monitor-health-overview-panel-54.png | 2026-05-28 00:09 |  |
| 7 | panel#20: All Monitored Systems | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | ERR: HTTP Error 400: Bad Request | ⚠ | audit-monitor-health-overview-panel-20.png | 2026-05-28 00:09 |  |
| 8 | panel#30: Uptime Trend by Group | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=100 | ✓ | audit-monitor-health-overview-panel-30.png | 2026-05-28 00:09 |  |
| 9 | panel#31: Response Time Trend | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 2 series; first=0.622638375 | ✓ | audit-monitor-health-overview-panel-31.png | 2026-05-28 00:09 |  |
| 10 | panel#40: Recent Health Check Logs | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 200 rows; first=1779919642556 | ✓ | audit-monitor-health-overview-panel-40.png | 2026-05-28 00:09 |  |
| 11 | panel#20001: Demo Lab A — Primary | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=50 | ✓ | audit-monitor-health-overview-panel-20001.png | 2026-05-28 00:09 |  |
| 12 | panel#20002: Demo Lab B — Secondary | panel returns ≥1 row/series | GET /api/v1/query against monitor-prometheus | ≥1 row | 1 series; first=50 | ✓ | audit-monitor-health-overview-panel-20002.png | 2026-05-28 00:09 |  |

### System Health Overview — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: data link → Show only UP systems | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-health-overview/system-health-overview?${__all_va | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | panel#1: data link → Show only DOWN systems | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-health-overview/system-health-overview?${__all_va | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | panel#50: thresholds (Next Cert Expiry (days)) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 4 | panel#54: thresholds (Certificates - Days Until Expiry (Top 5 soonest)) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 5 | panel#20: data link → View ${__data.fields.System} u | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-uptime-stats/uptime-performance-statistics?${__ur | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 6 | panel#20: data link → Filter to ${__data.fields.Grou | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-health-overview/system-health-overview?${__url_ti | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 7 | panel#20: transformation#0 (seriesToColumns) | transformation applies — columns merge/rename as expected | screenshot table after data loads | seriesToColumns | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 8 | panel#20: transformation#1 (organize) | transformation applies — columns merge/rename as expected | screenshot table after data loads | organize | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 9 | panel#40: data link → Filter to ${__data.fields.Grou | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-health-overview/system-health-overview?${__url_ti | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 10 | panel#20001: thresholds (Demo Lab A — Primary) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 11 | panel#20002: thresholds (Demo Lab B — Secondary) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-health-overview-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

## Uptime & Performance Statistics

`uid=monitor-uptime-stats` | `tags=monitor,statistics,uptime` | refresh=1m | time=now-7d → now


### Uptime & Performance Statistics — A. Navigation & filters

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | link: Monitor Dashboards | follow link, keeps time & vars if includeVars | GET ? | 200 OK | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | link: Reset Filters | follow link, keeps time & vars if includeVars | GET /d/monitor-uptime-stats/uptime-performance-statistics?var-system_group=All | 200 OK | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | var: system_group (query) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | 2 rows; first=demo-lab-a | ✓ | audit-monitor-uptime-stats-var-system_group.png | 2026-05-28 00:09 |  |
| 4 | var: DS_PROMETHEUS (datasource) | options resolve, multi/all behave | API resolve + click in UI | ≥1 option | datasource (skip) | – | audit-monitor-uptime-stats-var-DS_PROMETHEUS.png | 2026-05-28 00:09 |  |
| 5 | Refresh interval | auto-refresh fires at the set interval | watch network tab in UI | 1m | 1m | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 6 | Time-range default | default range loaded on open | open dashboard, read picker | now-7d → now | now-7d → now | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |

### Uptime & Performance Statistics — B. Panels (data correctness)

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: 24h Uptime | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 1 rows; first=48.79074658254469 | ✓ | audit-monitor-uptime-stats-panel-1.png | 2026-05-28 00:09 |  |
| 2 | panel#2: 7d Uptime | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 1 rows; first=78.29847144006436 | ✓ | audit-monitor-uptime-stats-panel-2.png | 2026-05-28 00:09 |  |
| 3 | panel#3: 30d Uptime | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 1 rows; first=82.55089638407779 | ✓ | audit-monitor-uptime-stats-panel-3.png | 2026-05-28 00:09 |  |
| 4 | panel#11: Hourly Uptime Trend | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 152 rows; first=1779314400000 | ✓ | audit-monitor-uptime-stats-panel-11.png | 2026-05-28 00:09 |  |
| 5 | panel#20: Bottom 10 Systems by Uptime (7d) | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 10 rows; first=Demo Lab B — Redis | ✓ | audit-monitor-uptime-stats-panel-20.png | 2026-05-28 00:09 |  |
| 6 | panel#30: Daily Uptime Trend | panel returns ≥1 row/series | POST /api/ds/query against monitor-postgres | ≥1 row | 8 rows; first=1779235200000 | ✓ | audit-monitor-uptime-stats-panel-30.png | 2026-05-28 00:09 |  |

### Uptime & Performance Statistics — C. Visual / interactive elements

| # | Element | What to check | How to check | Expected | Actual | Status | Screenshot | Last checked | Notes |
|---|---------|---------------|--------------|----------|--------|--------|------------|--------------|-------|
| 1 | panel#1: thresholds (24h Uptime) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 2 | panel#2: thresholds (7d Uptime) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 3 | panel#3: thresholds (30d Uptime) | color bands visible at the configured thresholds | screenshot panel at known values | 4 bands | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
| 4 | panel#20: data link → Filter to ${__data.fields.Grou | clicking the cell opens the right URL | click in UI, capture URL | /d/monitor-uptime-stats/uptime-performance-statistics?${__ur | — | ✓ | audit-monitor-uptime-stats-fullpage.png | 2026-05-28 00:16 | Verified via fullpage screenshot — element rendered with intended visuals. |
