# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.0.1] - 2026-05-31

First OSS release. Captures every change from the internal pre-release branch
under a single public-facing 0.0.1 tag. All notable items below.

### Added — real-data demo seed + bundled demo target containers
- **Every probe row in the seed now points at a real service** — both Lab A
  and Lab B. Where a public unauthenticated service exists (HTTP, TCP, ICMP,
  SSL, LDAP, Keycloak, gRPC, DNS, VERSION) each lab uses one. Where none
  exists (Postgres / MySQL / Redis / MongoDB / Elasticsearch), both labs
  point at the same locally-bundled container. Result: with the full
  profile, every dashboard panel shows live data; no placeholder DOWN rows.
- **Real public services** replace `example.com` placeholders:
  `ssl-demo-a` → `github.com:443`, `demo-b-web` → `https://play.grafana.org/`.
  Together with the already-real targets (`httpbin.org`, `1.1.1.1`,
  `ldap.forumsys.com`, `www.keycloak.org`, `grpcb.in`, `petstore3.swagger.io`).
- **Two intentional SSL negatives** added — `ssl-demo-expired`
  (`expired.badssl.com:443`) and `ssl-demo-selfsigned`
  (`self-signed.badssl.com:443`) — so the SSL expiry / chain-validation
  alerting can actually be observed firing in the demo dashboards.
- **Bundled "demo target" containers** for the probe types with no public
  unauthenticated service (Postgres / MySQL / Redis / MongoDB / Elasticsearch).
  Gated behind `COMPOSE_PROFILES=full` in docker-compose and
  `demoTargets.enabled` (default `false`) in the Helm chart. Default install
  stays lean (~600 MB lighter without ES); the full profile makes every
  dashboard panel show real UP data.
- **Result-pinning live tests** in `tests/live/test_prometheus_live.py` —
  `test_petstore_openapi_version_extracted`, `test_keycloak_org_probe_succeeds`,
  `test_grpcb_in_grpc_probe_succeeds`,
  `test_ssl_expired_badssl_correctly_flagged_negative`,
  `test_ssl_selfsigned_badssl_correctly_flagged_invalid`. These assert the
  *value* extracted from each real upstream, not just that the probe ran.

### Fixed
- `monitor_exporter/config.yml` Keycloak `base_url` was stale
  (`keycloak.example.com`); now matches the SQL seed (`www.keycloak.org`).
- Same fix mirrored into `deployments/k8s-helm/dev/monitor-grafana/config.yml`.

### Changed (breaking)
- **Internal metadata DB swapped from MariaDB 10.6 to Postgres 16.** All init
  scripts, Python modules, Grafana datasource provisioning, dashboard SQL,
  Helm chart, and AWS/GCP terraform starters now target Postgres. Env vars
  renamed `MARIADB_*` → `POSTGRES_*`; default host port `3307` → `5433`;
  driver `pymysql` → `psycopg 3`. See README + `.env.example` for the new
  configuration surface.

### Added
- Admin UI on port 9119 for CRUD of monitored systems, labs, and Grafana datasources.
- Prometheus HTTP-SD service (`/sd/<type>`) so the same exporter is the source
  of truth for Blackbox HTTP/TCP/ICMP/SSL/Node/gRPC/DNS scrape targets.
- `lab` and `datasource` tables in Postgres; admin UI is the editor.
- DB-backed dashboard template variables: adding a lab or datasource in the
  admin UI makes it appear in every dashboard's dropdown on next refresh.
- Repeat-by-`system_group` panels — new labs auto-create new tiles on the
  System Health Overview dashboard.
- New first-class system types: `POSTGRES`, `REDIS`, `MONGODB`,
  `ELASTICSEARCH`, `GRPC`, `DNS`.
- `datasource_sync` background job — reconciles the `datasource` table into
  Grafana via the HTTP API on a 60-second cycle.
- **Service Configuration dashboard** — embeds the admin UI inside Grafana via
  an iframe panel + "Open Admin UI (full screen)" link, so service/lab/datasource
  CRUD lives in the same browser tab as the dashboards.
- Cloud deployment starters under `deployments/aws/` and `deployments/gcp/`.
- Project restructure: everything under `deployments/{docker,k8s-helm,aws,gcp}/`.
- In-cluster Postgres template (`postgres.yaml`, gated by
  `postgres.deployInCluster`) so `helm install` works out of the box without
  requiring an external DB.
- Maintenance-window seed data (3 demo windows, 18 system links) so the
  Historical Data dashboard's maintenance panel isn't empty on first boot.
- Real public services in the demo seed for what works publicly: gRPC against
  `grpcb.in:9001`, Keycloak against `www.keycloak.org`, OpenAPI VERSION probe
  against the public Swagger Petstore.
- End-to-end live test (`tests/live/test_admin_ui_e2e_flow.py`) that proves
  the full admin UI → DB → HTTP-SD → Prometheus pipeline works.
- Tests: 240+ unit tests covering auth, CRUD, SD endpoints, probes, central
  DB connection helper.

### Changed
- Prometheus configuration switched from `file_sd_configs` to `http_sd_configs`
  pointing at the exporter on port 9119. No more YAML target file editing.
- Custom-check loops (LDAP/Keycloak/Database/Version) now read from the DB on
  every cycle instead of from `config.yml` on startup.
- Dashboards reference `$lab_group` instead of hardcoded environment labels.
- Helm chart Deployment now uses a `/sd/healthz` readiness probe to prevent
  Prometheus from losing its target set during exporter restarts.

### Fixed
- **`ssl-exporter` port binding** (`docker-compose.yml`). The container image
  defaults its listener to `:9219`, but the compose mapping exposed host port
  `9117 → container 9117` — a port nothing was listening on. Result: every
  Prometheus `ssl_certificates` scrape returned `connection refused`. Added
  `command: ["--web.listen-address=:9117"]` so the binary listens where
  Prometheus actually scrapes.
- **`health_check_history` retention cleanup** (`monitor_exporter/exporter.py`).
  The periodic delete used MariaDB-only `INTERVAL %s DAY` syntax which raised
  `syntax error at or near "$1"` every cycle on Postgres. The table grew
  unbounded until the fix. Replaced with `(%s || ' days')::interval` so
  psycopg parameterises cleanly.
- **`GRAFANA_PUBLIC_URL` default** (`docker-compose.yml`). Pointed at
  `localhost:3000` (the container port). Every alert-email deep-link landed on
  a dead port whenever the host port was overridden (the canonical setup uses
  `3030`). Now `${GRAFANA_PUBLIC_URL:-http://localhost:${GRAFANA_HOST_PORT:-3000}}`
  tracks the host-port mapping.
- **Helm `values.yaml` image references**
  (`deployments/k8s-helm/dev/monitor-grafana/values.yaml`). Four upstream
  public images (`prometheus`, `blackbox-exporter`, `ssl-exporter`,
  `grafana-oss`) carried a `ghcr.io/your-org/` prefix that doesn't resolve —
  a fresh `helm install` would `ImagePullBackOff` on all four. Switched to
  canonical docker.io paths; only `monitor-exporter` retains the placeholder
  because it's built locally.
- **`scripts/smoke-test.sh`** referenced removed services (Loki check,
  `e2e-trigger`, `monitor_e2e_pipeline_id`, `monitor_sonar_quality_gate_status`)
  and used the pre-`HOST_PORT` defaults (`3000`/`9090`). Rewritten against the
  current service set; defaults now match the actual docker-compose mapping
  (`3030`/`9091`); added a `/sd/http` probe.
- **`scripts/backup-monitor-db.sh`** invoked `mysqldump` against the Postgres
  backend (broken since the migration) and listed deleted tables
  (`e2e_test_run`, `sonar_analysis`). Re-implemented with `pg_dump`.

### Removed
- `helm/templates/monitor-exporter-config.yaml` no longer contains target
  lists — only runtime process settings. Targets live in `monitored_system`.
- `HealthCheckLogger.sync_systems()` — the DB is now canonical.
- Kustomize alt-deploy path under `k8s/` — Helm is canonical.
- **Lab Nodes** and **Node Monitoring** dashboards + the `NODE` `system_type`
  + `/sd/node` Prometheus HTTP-SD endpoint + the `lab_node_exporter` scrape
  job. ICMP probes for generic host availability remain supported.
- **E2E Test History / Overview / Trends** dashboards + `e2e_exporter.py`,
  `e2e_trigger.py` modules + `e2e_test_run`, `e2e_test_case` tables + port
  `9118` + `GITLAB_TRIGGER_TOKEN` / `TRIGGER_SHARED_SECRET` env vars.
- **Code Quality (SonarQube)** dashboard + `sonar_exporter.py` module +
  `sonar_analysis` table + `SONAR_TOKEN` env var + alert rules file.
- **Demo Lab B - Central Log Server** dashboard + Loki container + Loki
  datasource + `config/loki.yml` + `LOKI_HOST_PORT` env var.
- **Database Observability** dashboard (MySQL/MariaDB-specific, replaced by
  the generic DATABASE probe type).
- `system_version` column on `monitored_system` (orphan — never wired to a
  form field).
- One-shot migration scripts now that their inputs are gone:
  `scripts/migrate-yaml-to-db.py`, `scripts/maint/convert_promql_to_sql.py`,
  `scripts/maint/mysql_to_postgres_dashboards.py`.

### Security
- Removed plaintext database passwords from `helm/values/values-dev.yaml`.
- All credentials are now expected via env vars or Kubernetes Secrets; the
  committed values files only carry placeholders.
- Admin UI authentication delegates to Grafana (no second login system to
  secure).

