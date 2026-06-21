# scripts/

Operational shell + Python helpers for the Monitor stack. Each script is
self-documenting — `head -20 <script>` shows its usage block.

## Layout

| Path | Purpose |
|---|---|
| `backup-monitor-db.sh` | `pg_dump` the live Postgres into a gzipped SQL file, prune old backups, integrity-check the gzip. Cron-friendly. |
| `smoke-test.sh` | End-to-end health probe of the running stack (exporter, Prometheus, Grafana, blackbox). Non-zero exit on failure — use it as a deploy gate. |
| `maint/` | Re-runnable maintenance Python scripts (dashboard audit, panel-query checker, detailed per-panel report). See [`maint/`](#maint). |

## Conventions

- Shell scripts: `#!/usr/bin/env bash` + `set -euo pipefail`, kebab-case names, top-of-file usage block.
- Python scripts: `#!/usr/bin/env python3` + module docstring with usage block.
- All scripts read connection details from env vars with the docker-compose
  defaults baked in — no hard-coded hostnames or credentials.

## `maint/`

| Script | What it does |
|---|---|
| `audit_dashboards.py` | Walks every dashboard JSON, exercises each panel's backing query against live Grafana, and writes `docs/dashboard_audit.md`. Idempotent — preserves the manual `Notes` column on re-run. Has a `--verify` mode for regression-net CI. |
| `check_all_dashboards.py` | One-line OK/WARN/ERR per panel. Use for a fast sanity check after editing dashboards. |
| `detailed_dashboard_report.py` | Per-panel sample-row dump — useful when a panel is "no data" and you want to see what its query is actually returning. |

## Running

Examples assume the docker-compose stack is up and ports are at their defaults
(Postgres `5433`, Prometheus `9091`, Grafana `3030`).

```bash
# Daily backup, keep last 14 days
RETENTION_DAYS=14 ./scripts/backup-monitor-db.sh

# Stack health gate before declaring a deploy successful
./scripts/smoke-test.sh

# Refresh the dashboard audit (preserves manual notes)
python3.11 scripts/maint/audit_dashboards.py

# Regression check against the last audit run
python3.11 scripts/maint/audit_dashboards.py --verify
```
