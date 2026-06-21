# Full-stack system audit — monitor-grafana

_Generated 2026-05-28. Audit-only — no code changes were made by the audit itself._

This report covers the whole stack: Python exporter, admin UI, Postgres schema, dashboards, Prometheus / Blackbox / Grafana configs, Docker compose, Helm + AWS + GCP + Cloud Run overlays, CI, tests, secrets, and docs. Dashboards are covered at stack-level only — see `docs/dashboard_audit.md` for the panel-by-panel report.

Severity legend: `CRITICAL` · `HIGH` · `MEDIUM` · `LOW` · `INFO`.

## Resolved since this snapshot (2026-05-30)

These rows have been addressed; the table bodies are left intact for traceability.

- **Row 7.8** (CLAUDE.md "Five tables" drift) — now reads "Eight tables" with the missing `email_log`, `maintenance_window`, `maintenance_window_system` rows.
- **Row 7.9** (CLAUDE.md "init-db files 01→09" drift) — now reads "01, 06–10" and the per-file list includes `10-seed-demo-history.sql`.
- **Keycloak fallback URL** (related to row 7.13) — `monitor_exporter/config.yml` and `deployments/k8s-helm/dev/monitor-grafana/config.yml` no longer ship `keycloak.example.com`; both point at `https://www.keycloak.org` matching the SQL seed.
- **Placeholder demo data** (informally raised in the executive summary) — every probe row in the seed now points at a real public service or a bundled demo target container (`COMPOSE_PROFILES=full` / `demoTargets.enabled=true`). See CHANGELOG `[Unreleased]` for the full list.
- **Test count** is now 278 (was 270 when this audit was written); the new tests are documented in the CHANGELOG and the live suite has new `test_bundled_db_probe_is_up` parametrized cases.

Still open from the original audit: rows 5.1 / 5.2 (Grafana `admin/admin` default), 6.1 (`ADMIN_UI_SECRET_KEY` Helm `optional: true`), 6.4 (no NetworkPolicy in Helm chart), 1.2 (SSRF surface on probe targets), 2.1 / 2.2 / 2.3 (admin-UI secret-key weak defaults), datasource_sync `password_env` exfil surface.

---

## Executive summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2 |
| HIGH     | 7 |
| MEDIUM   | 11 |
| LOW      | 7 |
| INFO     | many (each section ends with green-light items) |

### Top 5 issues by impact

1. **CRITICAL** — Grafana admin password committed as plaintext `admin` in `config/grafana.ini:22` and `config/grafana-docker.ini:7`. A clone of the repo on a server with the bundled provisioning files = instant admin access.
2. **CRITICAL** — `docker-compose.yml:124` ships a fallback `GF_SECURITY_ADMIN_PASSWORD=admin` for Grafana, compounding finding #1 when `.env` is missing.
3. **HIGH** — `monitor_exporter/datasource_sync.py:71` trusts admin-UI-supplied `password_env` — an admin-UI user can name any env var (e.g. `ADMIN_UI_SECRET_KEY`, `GRAFANA_SA_TOKEN`) and the exporter will publish its value as a datasource password to Grafana.
4. **HIGH** — `monitor_exporter/sd_endpoints.py` (`/sd/*` routes) is unauthenticated. Any client that reaches `:9119` gets the full target catalog (URLs, IPs, ports). Designed for Prometheus internal scrape; risky if `:9119` is ever exposed beyond the cluster network.
5. **HIGH** — Cloud overlays pin `tag: latest` (`deployments/aws/values-aws.yaml:18`, `deployments/gcp/values-gcp.yaml:16`) — rolls are not reproducible and `helm rollback` is not deterministic.

### Items NOT flagged (verified as correct, contrary to first-pass guesses)

- CLAUDE.md says "270+ tests" — actual count `270` (28 test files). **No drift.**
- Prometheus HTTP-SD is correctly wired at `monitor-exporter:9119` (`config/prometheus-docker.yml:28,47,64`).
- Helm chart has `readinessProbe` and `livenessProbe` on the monitor-exporter pod, hitting `/sd/healthz` (per CLAUDE.md requirement).
- `.env` is correctly listed in `.gitignore`; only `.env.example` is committed.
- Dockerfiles run as non-root (`USER 1001` in both `Dockerfile.monitor-exporter` and `Dockerfile.smtp-to-graph`).
- `docker-compose.yml` pins every image to a specific tag (`postgres:16-alpine`, `prom/prometheus:v2.54.1`, `prom/blackbox-exporter:v0.25.0`, `ribbybibby/ssl-exporter:2.4.3`, `grafana/grafana-oss:11.4.0`). No `:latest` in compose.

---

## 1. Backend — Python exporter

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 1.1 | `exporter.py` size | single-file god-object? | < 600 LOC per module | 1182 LOC | MEDIUM | `monitor_exporter/exporter.py` | Mixes LDAP, Keycloak, version detection, DB probes, check loop, main entry. Candidate for split into `probes/` subpackage. |
| 1.2 | SSRF surface on probe targets | host/port from DB rows is reachable from exporter process | allowlist or deny-internal IPs | none — DB row trusted as-is | HIGH | `monitor_exporter/exporter.py:688,761,789,814` (socket.create_connection) | An admin-UI user who can create a monitored_system row can probe AWS metadata (`169.254.169.254`), localhost, RFC-1918. Defence-in-depth needed if admin-UI ever lowers its auth bar. |
| 1.3 | `HealthCheckLogger.__init__` hardcoded password default | required env-var, not silent default | `"password"` literal | MEDIUM | `monitor_exporter/exporter.py:155` | Constructor silently runs with a known default if env vars missing. |
| 1.4 | Bare `except Exception:` blocks | logged with `.exception` not `.warning` | 11 sites | MEDIUM | `monitor_exporter/exporter.py:198,228,253,475,929,1027,1093,1121` + `admin_ui.py:323` + `datasource_sync.py:148` | Stack-trace info lost; harder to diagnose intermittent failures. |
| 1.5 | No connection pool in `db.py` | psycopg pool / reused conn | new `connect()` per caller | MEDIUM | `monitor_exporter/db.py` (54 LOC) | Bursty admin-UI traffic + SD endpoint cache miss can exhaust Postgres `max_connections`. |
| 1.6 | Type hints on public functions | every public fn typed | mixed — `_shape_target`, `_base_target`, `_load_db_targets` untyped | LOW | `monitor_exporter/exporter.py:983–1042` | Shape contracts are implicit. |
| 1.7 | Duplicated version-extract logic | shared helper | 5x copy-paste blocks (Spring / OpenAPI / Camunda / Gateway / JSON) | LOW | `monitor_exporter/exporter.py:512–637` | DRY candidate. |
| 1.8 | Cycle-duration observability | `monitor_check_cycle_duration_seconds` | absent | INFO | `monitor_exporter/exporter.py` | Only `is_up` / `response_time_ms` gauges. Cycle slowness is invisible. |
| 1.9 | Python deps freshness | all current within ~6 months | `requirements.txt` pinned to fall-2024 versions | INFO | `monitor_exporter/requirements.txt` | All eight packages pinned (`Flask==3.0.3`, `psycopg[binary]==3.2.3`, …); review window ~6 months from generation date. |

Green-light: every SQL statement uses parameterized queries (no f-string SQL); none of the dangerous deserialization or shell-out idioms appear anywhere in `monitor_exporter/*.py` (`grep -nE 'eval\(|exec\(|os\.system|subprocess\.' monitor_exporter/*.py` returns empty).

---

## 2. Admin UI & auth

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 2.1 | Flask `secret_key` fallback | env-required, fail-fast on missing | `dev-only-change-me` literal | HIGH | `monitor_exporter/admin_ui.py:675` | Session-cookie signature is predictable if env-var absent. |
| 2.2 | Compose env default for the same key | same — fail-fast | `change-me-in-prod` literal | HIGH | `docker-compose.yml:106` | `:-change-me-in-prod` runs the stack with weak secret when `.env` missing. |
| 2.3 | Helm marks `ADMIN_UI_SECRET_KEY` as `optional: true` | secret required (`optional: false`) | `optional: true` (pod boots without it) | HIGH | `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-exporter-deployment.yaml` line 95 | If the Secret is missing in the namespace, the pod starts with no secret → admin-UI sessions silently insecure. |
| 2.4 | Grafana session check is the only auth wall | network-layer + cookie check | cookie check only | MEDIUM | `monitor_exporter/admin_ui.py:305–327` | Auth correctness depends on `GRAFANA_INTERNAL_URL` being right. If misconfigured to a stub that always 200s, admin UI is wide open. |
| 2.5 | `_coerce()` swallows ValueError → `None` | distinguish "blank" from "invalid" | both map to `None` | MEDIUM | `monitor_exporter/admin_ui.py:246–249` | Forms accept "not-a-number" silently. |
| 2.6 | `create_blueprint()` length | < 200 LOC | 283 LOC, 27 nested routes | LOW | `monitor_exporter/admin_ui.py:373–655` | Split labs/datasources into sub-blueprints. |
| 2.7 | Per-route metrics / request log | counters + latency histogram | none (werkzeug suppressed) | INFO | `monitor_exporter/admin_ui.py:676` | No `monitor_admin_ui_request_total` for alerting. |

Green-light: every CRUD route uses `@require_grafana_auth`; the validation pipeline (`_validate`, `_form_to_row`, `REQUIRED_FIELDS`, `ALL_FIELDS`) is consistent and enumerated.

---

## 3. Data layer (Postgres schema + seeds)

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 3.1 | FK on `monitored_system.lab_group` → `lab.name` | FK present | VARCHAR free-text, no FK | MEDIUM | `docker/init-db/06-extend-monitored-system.sql:22` | Deleting a `lab` row leaves orphaned `monitored_system.lab_group` values. App keeps working but dashboards may show ghost labs. |
| 3.2 | CHECK constraint on `system_type` enum | DB-level enforcement | none — validation only in `admin_ui.SYSTEM_TYPES` | MEDIUM | `docker/init-db/01-schema.sql` + `monitor_exporter/admin_ui.py:29` | Direct SQL insert can produce an unknown `system_type`. |
| 3.3 | CHECK constraint on `node_type` / `version_strategy` | DB-level enforcement | none | LOW | same | Same risk pattern as 3.2. |
| 3.4 | Seed-file numerical ordering | linear chain of deps | 01, 06, 07, 08, 09, 10 (5 of 6 jumps work) | INFO | `docker/init-db/` ls | Postgres runs init files alphabetically; current numbering is correct but leaves gaps (no 02–05). Cosmetic. |
| 3.5 | `10-seed-demo-history.sql` idempotency | runs cleanly on volume reset | NOT idempotent by design (init-only) | INFO | `docker/init-db/10-seed-demo-history.sql:9` | Postgres only runs init files on first start; documented. |
| 3.6 | Hot-column indexes | FK + status + timestamp covered | covered: `idx_system_group`, `idx_hch_system_id`, `idx_hch_check_ts`, `idx_hch_status`, `idx_as_system_id`, `idx_as_status`, `idx_type_enable` | INFO | `docker/init-db/01-schema.sql:16,28-30,43-44`, `06-extend-monitored-system.sql:27-28` | ✓ |

Green-light: every FK that's needed (history → system, alert_state → system, maintenance_window_system → both) is present.

---

## 4. Dashboards (stack-level)

The 6 dashboards under `dashboards/` already have a panel-by-panel audit in `docs/dashboard_audit.md` (240 lines, 7 screenshots committed). This section covers only stack-level concerns.

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 4.1 | All dashboards `editable: true` | locked in prod | all 6 are `editable: true` | LOW | `dashboards/*.json` (alert-history:18, service-configuration:3, historical-data:18, ssl-certificates:29, system-health-overview:29, uptime-statistics:29) | Provisioned dashboards should be `false` to prevent UI drift. |
| 4.2 | `uid` prefix `monitor-` per CLAUDE.md | all 6 prefixed | ✓ all 6: `monitor-alert-history`, `monitor-health-overview`, `monitor-historical`, `monitor-service-config`, `monitor-ssl-certs`, `monitor-uptime-stats` | INFO | each JSON | ✓ |
| 4.3 | SQL dialect | Postgres-only | confirmed Postgres syntax throughout (per `docs/dashboard_audit.md`) | INFO | dashboards + audit doc | No MariaDB-isms detected. |
| 4.4 | Vestigial datasource var `DS_MARIADB` | removed | gone — only `DS_PROMETHEUS` remains as a datasource var | INFO | dashboard audit row 5 | ✓ |
| 4.5 | Cross-dashboard links target real UIDs | every link resolves | not auto-verified at stack-level (covered in `docs/dashboard_audit.md` Layer 3) | – | n/a | See dashboard_audit.md table D. |

---

## 5. Infrastructure & configs

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 5.1 | **Grafana admin password in repo** | env-only | `admin_password = admin` committed | **CRITICAL** | `config/grafana.ini:22`, `config/grafana-docker.ini:7` | Plaintext. Both files version-controlled. |
| 5.2 | **Compose Grafana admin fallback** | no fallback | `:-admin` | **CRITICAL** | `docker-compose.yml:124` | Compose `up` works with no `.env` and Grafana boots with `admin/admin`. |
| 5.3 | Compose Postgres password fallback | no fallback | `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-monitoring}` | HIGH | `docker-compose.yml:21` | Same pattern as 5.2 for DB. |
| 5.4 | Image pinning in compose | versioned tags | postgres:16-alpine, prom/prometheus:v2.54.1, blackbox:v0.25.0, ssl-exporter:2.4.3, grafana-oss:11.4.0 | INFO | `docker-compose.yml:16,38,56,69,120` | ✓ |
| 5.5 | Ports exposed beyond need | only Grafana/admin-UI public | also publishes 9090 (Prom), 9115 (Blackbox), 9116/9119 (exporter), 9117 (SSL) | MEDIUM | `docker-compose.yml` ports blocks | Acceptable in local dev; should not pattern-match prod compose. |
| 5.6 | Healthchecks on compose services | every service has one | only Postgres has explicit healthcheck | LOW | `docker-compose.yml:27-32` | Other services rely on K8s-style liveness only when on Helm. |
| 5.7 | Prometheus HTTP-SD wired | `monitor-exporter:9119/sd/*` | ✓ http/tcp/icmp/ssl/grpc/dns | INFO | `config/prometheus-docker.yml:27-28,46-47,63-64,…` | ✓ |
| 5.8 | Blackbox modules complete | http_2xx, tcp_connect, icmp_ping, grpc, dns at minimum | present: http_2xx, http_2xx_or_401, http_302, http_401, tcp_connect, icmp_ping, grpc, grpc_plain, dns_udp, dns_tcp | INFO | `config/blackbox.yml:1-84` | ✓ |
| 5.9 | "Alert rules" file naming | actual alert rules | `config/alert_rules/*.yml` contain **recording rules only** (use `record:` not `alert:`) | LOW | `config/alert_rules/health_check_rules.yml:8-13`, `ssl_rules.yml` | Naming is misleading. Actual alerts live in Grafana unified alerting (`config/provisioning/alerting/`). Rename or document. |
| 5.10 | Grafana provisioning structure | alerting/dashboards/datasources subdirs | all three present | INFO | `config/provisioning/` | ✓ |

---

## 6. Deployments (Helm / AWS / GCP / Cloud Run)

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 6.1 | Helm: `ADMIN_UI_SECRET_KEY` optional Secret ref | required | `optional: true` | HIGH | `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-exporter-deployment.yaml` line 95 | Pod boots without secret. Make required or fail Helm install via `required` template func. |
| 6.2 | AWS overlay pins `tag: latest` | versioned tag | `latest` | HIGH | `deployments/aws/values-aws.yaml:18` | Rolls non-deterministic. |
| 6.3 | GCP overlay pins `tag: latest` | versioned tag | `latest` | HIGH | `deployments/gcp/values-gcp.yaml:16` | Same. |
| 6.4 | NetworkPolicy in chart | east-west traffic restricted | no `NetworkPolicy` resources found | HIGH | `deployments/k8s-helm/dev/monitor-grafana/templates/` (no policy files) | All pods can reach all pods. Combined with finding 4 (unauth `/sd/*`) this means any other pod in the namespace can scrape the target catalog. |
| 6.5 | Readiness probe on `/sd/healthz` | required per CLAUDE.md | ✓ present | INFO | `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-exporter-deployment.yaml:114-122` | ✓ |
| 6.6 | `readOnlyRootFilesystem` on stateless probers | true | not set on Prometheus/Blackbox/SSL/Exporter | MEDIUM | `deployments/k8s-helm/dev/monitor-grafana/templates/*-deployment.yaml` | Containers writable at runtime; add `readOnlyRootFilesystem: true` for stateless services. |
| 6.7 | Cloud Run exposes only `:9119` (admin UI + SD) | metrics port also exposed | port 9116 (`/metrics`) not exposed | MEDIUM | `deployments/gcp/cloud-run/service.yaml:25` | Prometheus elsewhere must scrape the SD only. Acceptable trade-off; document. |
| 6.8 | Cloud Run secrets via env vars | secretKeyRef volume | env-var refs (logged at startup) | HIGH | `deployments/gcp/cloud-run/service.yaml:39-51` | Cloud Run audit log captures env. Use Secret Manager volume mounts. |
| 6.9 | runAsNonRoot on all pods | true | ✓ all chart deployments set `runAsNonRoot: true` | INFO | `deployments/k8s-helm/dev/monitor-grafana/templates/*-deployment.yaml` | ✓ |
| 6.10 | Datasource passwords use Grafana env-var refs (`${GF_DS_…}`) per CLAUDE.md | required pattern | ✓ `config/provisioning/datasources/datasources-docker.yml:31`, Helm `templates/grafana-provisioning.yaml:37` | INFO | (cited) | ✓ |

---

## 7. CI, tests, secrets, docs

| # | Item | Check | Expected | Actual | Severity | Evidence | Notes |
|---|------|-------|----------|--------|----------|----------|-------|
| 7.1 | Two parallel CI systems | one canonical | both `.github/workflows/test.yml` AND `.gitlab-ci.yml` maintained | MEDIUM | files cited | Drift risk. Pick one or document which is canonical and run the other as a smoke. |
| 7.2 | Test count | matches CLAUDE.md "270+ tests" | 270 funcs across 28 files | INFO | `find tests -name 'test_*.py' -exec grep -c ^def\ test_` | ✓ Accurate (not "225" as one explorer claimed). |
| 7.3 | Test coverage — `datasource_sync` error paths | timeouts, 401, conflicts | only happy path tested | MEDIUM | `tests/unit/test_datasource_sync.py` | Add error-path tests for `_diff` mismatches, Grafana API non-200, password_env missing. |
| 7.4 | Test coverage — admin UI RBAC edge cases | concurrent edits, deleted-lab URL | not covered | MEDIUM | `tests/unit/test_admin_ui_auth.py`, `test_admin_ui_labs.py` | Add tests for: stale lab in URL, concurrent create, malformed cookie. |
| 7.5 | Live tests gating | `--live` flag enforced | ✓ `pytestmark = pytest.mark.live` in every live file | INFO | `tests/live/*.py` | ✓ |
| 7.6 | `.env.example` shape vs `.env` gitignore | only example committed | ✓ `.env` ignored via `.gitignore`; `.env.example` placeholders use `change-me` | INFO | `.env.example` lines 10,31,37,42,48,55 | ✓ |
| 7.7 | `ADMIN_UI_SECRET_KEY` placeholder guidance | concrete suggestion | `.env.example:55` → `generate-with-python-secrets-token_urlsafe-32` | INFO | (cited) | ✓ Helpful prompt. |
| 7.8 | CLAUDE.md "Five tables in monitoring" | matches schema | actually 8 (lab, monitored_system, datasource, health_check_history, alert_state, email_log, maintenance_window, maintenance_window_system) | LOW | `docker/init-db/01-schema.sql` + `06-extend-monitored-system.sql` + `08-datasource-and-new-types.sql` | Doc drift: CLAUDE.md line 99 says "Five tables". |
| 7.9 | CLAUDE.md "init-db files 01→09" | matches dir | actually 01,06,07,08,09,10 | LOW | `docker/init-db/` ls | Doc drift: CLAUDE.md line 170 says "01→09"; `10-seed-demo-history.sql` is the seed for the historical-data dashboard. |
| 7.10 | `smoke-test.sh` Grafana port default | matches compose default | script defaults to 3030; compose defaults to 3000 (overridable via `GRAFANA_HOST_PORT`) | LOW | `scripts/smoke-test.sh:17`, `docker-compose.yml:150` | Inconsistency, not a bug — env-var override works. |
| 7.11 | `scripts/maint/audit_dashboards.py` matches `docs/dashboard_audit.md` shape | round-trip stable | matches (preserves manual `Notes`, refreshes Actual/Status) | INFO | `scripts/maint/audit_dashboards.py` (451 LOC) + `docs/dashboard_audit.md` (240 lines) | ✓ |
| 7.12 | "TODO/FIXME/XXX" in docs | none | zero | INFO | `docs/` | ✓ |
| 7.13 | `docs/SECURITY.md` pre-publish checklist | still applicable | yes (env-var only, no plaintext tokens) | INFO | `docs/SECURITY.md` | ✓ But findings 5.1/5.2 violate the checklist — the doc and the repo state disagree. |

---

## Cross-references

- **Dashboard panel-by-panel audit** — `docs/dashboard_audit.md` (Layers A–D for each of the 6 dashboards). Screenshots in `docs/screenshots/`.
- **Authoritative project guide** — `CLAUDE.md` (architecture, conventions, gotchas). See findings 7.8 and 7.9 for drift.
- **Security checklist** — `docs/SECURITY.md` (env-var policy; violated by findings 5.1 / 5.2 / 7.13).
- **Runbook** — `docs/runbook.md` (alert response procedures; not audited row-by-row here).

## How to re-run the audit

```bash
# Spot-check every CRITICAL/HIGH row
grep -n 'admin_password' config/grafana*.ini
grep -n 'change-me-in-prod\|dev-only-change-me' docker-compose.yml monitor_exporter/admin_ui.py
grep -n 'password_env' monitor_exporter/datasource_sync.py
grep -n 'tag: latest' deployments/aws/values-aws.yaml deployments/gcp/values-gcp.yaml
grep -rn 'NetworkPolicy' deployments/k8s-helm/

# Re-confirm the green-light items (do not regress)
find tests -name 'test_*.py' -exec grep -c '^def test_\|^async def test_' {} + | awk -F: '{s+=$2} END {print s}'  # expect 270
grep -n 'http_sd_configs\|monitor-exporter:9119' config/prometheus-docker.yml                                     # expect ≥6 references
grep -n 'runAsNonRoot' deployments/k8s-helm/dev/monitor-grafana/templates/*-deployment.yaml                       # every pod true

# Tests + dashboard maintenance
pytest tests/unit tests/dashboards tests/config tests/db -q
python3.11 scripts/maint/check_all_dashboards.py
```

## Out of scope

- Fixing any of the findings (audit-only mode, per user choice). Each row is intended to be triaged into follow-up tickets.
- Live integration tests (`pytest tests/live --live`) — require the stack to be running.
- Performance benchmarks, visual regression, cross-browser checks.
