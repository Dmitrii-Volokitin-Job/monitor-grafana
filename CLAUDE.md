# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working with this repository.

## Project Overview

Open-source monitoring stack: Grafana + Prometheus + a custom Python exporter
that exposes a **database-driven admin UI** so users add monitored services
and labs through a web form instead of editing YAML.

The whole catalog (monitored systems, labs, Grafana datasources) lives in a
`monitored_system` / `lab` / `datasource` table set in **Postgres 16**. The
exporter serves that catalog to Prometheus via HTTP Service Discovery on port
9119, so adding a service in the UI propagates to Prometheus within ~30 s —
no `/-/reload`, no file edits, no pod restarts.

Supported probe types out of the box: HTTP, TCP, ICMP, SSL, LDAP, Keycloak,
DATABASE (MySQL/MariaDB handshake), Postgres, Redis, MongoDB, Elasticsearch,
gRPC, DNS, Version detection (Spring Actuator / OpenAPI / Kubernetes / Camunda
/ Gateway / JSON / Monitor).

## Repo layout

```
.
├── monitor_exporter/     # Python exporter package
│   ├── exporter.py            # main entry; LDAP/Keycloak/DB/Version checks (DB-driven)
│   ├── admin_ui.py            # Flask Blueprint on :9119, CRUD for systems/labs/datasources
│   ├── sd_endpoints.py        # Prometheus HTTP-SD on :9119 (same Flask app)
│   ├── datasource_sync.py     # reconciles `datasource` table into Grafana via API
│   ├── templates/             # Jinja2 templates for admin UI
│   └── config.yml             # process-level settings + optional poller config
├── dashboards/                # Grafana dashboard JSON (auto-provisioned)
├── config/
│   ├── prometheus.yml         # native (non-Docker) Prometheus config
│   ├── prometheus-docker.yml  # Docker variant — points HTTP-SD at monitor-exporter:9119
│   ├── blackbox.yml           # Blackbox modules: http_2xx, tcp_connect, icmp_ping, grpc, dns_udp, …
│   └── targets/               # legacy YAML; consumed ONLY by scripts/migrate-yaml-to-db.py
├── docker/
│   ├── init-db/0N-*.sql       # Postgres schema + seed (alphabetical order: 01, 06–10)
│   └── Dockerfile.monitor-exporter
├── smtp_to_graph/             # sidecar: SMTP → Microsoft Graph (kept generic; usable only if
│                              # your tenant uses Graph for mail egress, can be ignored otherwise)
├── docker-compose.yml         # local dev stack (root; symlinked from deployments/docker/)
├── deployments/
│   ├── docker/                # symlinks pointing to root files for ergonomic `cd`
│   ├── k8s-helm/              # Helm chart (canonical artefact for K8s/OpenShift)
│   ├── aws/                   # EKS + RDS terraform starter + values overlay
│   └── gcp/                   # GKE + Cloud SQL starter + Cloud Run alt path
├── tests/
│   ├── unit/                  # fast, mocked
│   ├── dashboards/            # JSON schema + PromQL syntax validators
│   └── live/                  # gated by --live; requires `docker compose up`
├── docs/
│   ├── runbook.md             # what to do when each alert fires + admin UI walkthrough
│   └── SECURITY.md            # vulnerability reporting + secret handling
├── scripts/
│   ├── migrate-yaml-to-db.py  # one-time YAML→DB importer (idempotent)
│   ├── smoke-test.sh
│   └── backup-monitor-db.sh
├── README.md                  # user-facing
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── LICENSE                    # Apache 2.0
└── .env.example
```

## Commands

```bash
# Local dev stack — lean default
docker compose up -d

# Local dev stack — FULL profile (starts 5 bundled real-target containers:
# postgres / mysql / redis / mongo / elasticsearch). The seed's demo-a-* and
# demo-b-* DB rows point at these hostnames so every dashboard panel shows
# real UP data. Costs ~600 MB more RAM (mostly ES).
COMPOSE_PROFILES=full docker compose up -d

docker compose down
docker compose logs -f monitor-exporter

# Endpoints
open http://localhost:3000                              # Grafana (admin/admin)
open http://localhost:9119/admin/                       # CRUD systems/labs/datasources
curl http://localhost:9119/sd/http | jq                 # what Prometheus sees
curl http://localhost:9119/sd/healthz                   # liveness
curl http://localhost:9116/metrics | grep monitor_         # exporter metrics

# Tests
pip install -r requirements-test.txt
pytest tests/unit                                       # fast
pytest tests/dashboards                                 # dashboard JSON validators
pytest tests/live --live                                # requires docker compose up

# One-time YAML→DB migration (only needed when upgrading from an old install
# that still had targets in config/targets/*.yml — clean installs skip this)
POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=monitoring \
POSTGRES_PASSWORD=monitoring \
  python scripts/migrate-yaml-to-db.py
```

## Database schema

Eight tables in `monitoring`:

| Table              | Edited by             | Read by                                  |
|--------------------|-----------------------|------------------------------------------|
| `lab`              | admin UI / SQL seed   | dashboards (dropdowns), admin UI         |
| `monitored_system` | admin UI / SQL seed   | exporter checks, SD endpoints, dashboards|
| `datasource`       | admin UI / SQL seed   | dashboard dropdowns, datasource_sync     |
| `health_check_history` | exporter          | Health Check Logs panels                 |
| `alert_state`      | exporter / webhook    | Alert History dashboard                  |
| `email_log`        | webhook / smtp_to_graph | Alert History dashboard (email rail)   |
| `maintenance_window` | admin UI / SQL seed | Historical Data dashboard maintenance panel |
| `maintenance_window_system` | admin UI / SQL seed | join: which systems each window covers |

Per-type column usage on `monitored_system`:

| system_type     | url               | db_host/db_port | extra                |
|-----------------|-------------------|-----------------|----------------------|
| HTTP            | full URL          | —               | `blackbox_module`    |
| TCP             | host:port         | —               | `blackbox_module`    |
| ICMP / NODE     | IP                | —               | `node_id`, `node_name`, `lab_group`, `node_type` |
| SSL             | host:port         | —               | `cert_alias`, `cert_description` |
| LDAP            | ldap[s]://uri     | —               | —                    |
| KEYCLOAK        | base URL          | —               | `realm_path`         |
| DATABASE        | display only      | required        | MySQL/MariaDB handshake |
| POSTGRES        | display only      | required        | —                    |
| REDIS           | display only      | required        | —                    |
| MONGODB         | display only      | required        | —                    |
| ELASTICSEARCH   | base URL          | —               | —                    |
| GRPC            | host:port         | —               | `blackbox_module` (grpc / grpc_plain) |
| DNS             | resolver IP       | —               | `blackbox_module` (dns_udp / dns_tcp) |
| VERSION         | endpoint URL      | —               | `version_strategy`   |

Required-field matrix lives in `admin_ui.REQUIRED_FIELDS` — keep it in sync if
you add a type.

## Tech Stack

Python 3.11 (exporter + Flask + httpx + psycopg 3 + aiosmtpd), Prometheus 2.54,

## Conventions

- **Dashboard `uid` prefix is `monitor-`** — used in cross-dashboard links.
- **Datasource UIDs** follow `monitor-<type>[-<lab>]` (e.g. `monitor-postgres-demo-a`).
  The internal monitoring DB is always `monitor-postgres`.
- **Adding a target = clicking "+ New system" in the admin UI.** The exporter
  rereads `monitored_system` every cycle and Prometheus refreshes HTTP-SD
  every 30 s. The legacy `config/targets/*.yml` files are kept ONLY as input
  to `scripts/migrate-yaml-to-db.py` — they are NOT read at runtime.
- **Dashboard variables are SQL queries against the `lab` + `datasource`
  tables.** Adding a row in the admin UI makes the dropdown reflect it on
  next dashboard load. The overview dashboard uses `repeat: "system_group"`
  on its per-lab stat tile, so a new lab auto-creates a new tile.
- **Each Python module exposes a `start_*()` function** invoked from
  `exporter.py main()` in a daemon thread. The main thread sleeps.
- **Tokens / passwords come from env vars** (see `.env.example`). Never
  commit a real credential — see `docs/SECURITY.md` for the pre-publish
  checklist.
- **Demo seed targets real services.** Every row in `docker/init-db/*.sql`
  points at a real, reachable service so dashboards show live data on first
  boot — not placeholder DOWNs. Public services used: `httpbin.org`,
  `dns.google:53`, `one.one.one.one:53`, `1.1.1.1`, `8.8.8.8`, `github.com:443`,
  `ldap.forumsys.com:389`, `www.keycloak.org`, `grpcb.in:9001`,
  `petstore3.swagger.io`, `play.grafana.org`. Two SSL rows are intentionally
  broken negatives (`expired.badssl.com`, `self-signed.badssl.com`) so the
  SSL alerting pipeline can be observed firing — see `docs/runbook.md`.
- **DB-style probes (Postgres/MySQL/Redis/Mongo/ES) use bundled containers**
  because no public unauthenticated service exists. The containers are gated
  behind `COMPOSE_PROFILES=full` in docker-compose and `demoTargets.enabled`
  (default `false`) in the Helm chart. The seed rows point at hostnames like
  `demo-postgres-target`, `demo-mysql-target`, `demo-redis-target`,
  `demo-mongo-target`, `demo-es-target` — these only resolve when the
  corresponding profile/values toggle is on. Lean default install: those
  probes show DOWN. Full profile: every dashboard panel has live data.

## Pitfalls / gotchas

- **Admin UI / SD endpoints (:9119) are a hard Prometheus dependency.** If
  the exporter pod is down, Prometheus loses its blackbox/SSL/node target
  set after one HTTP-SD refresh (~30 s). Helm chart has a readiness probe
  on `/sd/healthz` so K8s won't route to a half-started pod; Prometheus
  uses the last good response between scrapes.
- **Admin UI requires Grafana basic auth enabled** (anonymous mode off).
  docker-compose already sets `GF_SECURITY_ADMIN_PASSWORD`; on K8s the
  Secret must include the same key. Without a logged-in Grafana user, the
  admin UI 302s to `${GRAFANA_PUBLIC_URL}/login`.
- **Datasource passwords use Grafana env-var refs** inside the chart
  (`password: ${GF_DS_POSTGRES_PASSWORD}`), NOT Helm `{{ .Values… }}`
  substitution. The env vars come from a Secret. This keeps the rendered
  ConfigMap free of plaintext passwords.
- **Init-db file ordering matters.** Postgres runs `docker/init-db/*.sql`
  alphabetically. Current numbering:
  - `01-schema.sql` — base tables
  - `06-extend-monitored-system.sql` — adds type-discriminated columns + `lab`
  - `07-seed-systems.sql` — demo systems + labs (real public services + SSL negatives)
  - `08-datasource-and-new-types.sql` — `datasource` table
  - `09-seed-new-types-and-datasources.sql` — Postgres/Redis/Mongo/ES/gRPC/DNS demos
  - `10-seed-demo-history.sql` — backfilled synthetic check history (init-only, NOT idempotent by design)
  New schemas must pick a number after their deps.
- **Helm chart re-embeds the same SQL.** `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-db-init.yaml`
  carries a copy of all `docker/init-db/*.sql` content as a ConfigMap. Any
  edit to a seed file MUST be mirrored there or the K8s install diverges
  from docker-compose. There's no auto-sync — it's a manual contract.
- **`tests/live/*` only runs with `--live`.** Without the flag the marker
  filters them out — a "0 tests collected" result from `pytest tests/live`
  is expected, not a failure.
- **Grafana dashboard provisioning has a ~10 s reload latency.** Editing a
  file under `dashboards/` and immediately rendering via the image-renderer
  often captures the PREVIOUS query result — provisioned dashboards are
  re-read on the next watcher tick, not on file save. Symptom: the rendered
  PNG shows old data even though the JSON on disk has the new query. Fix:
  before `curl /render/d/<uid>`, verify Grafana sees the change by hitting
  `/api/dashboards/uid/<uid>` and grepping for a unique substring of the
  new query. Don't skip this step or you'll commit stale screenshots and
  burn an amend cycle. The full workflow is in
  `~/.claude/skills/grafana-screenshot-pipeline/SKILL.md`.
- **Dashboard SQL is Postgres dialect.** The internal `monitoring` DB is
  Postgres 16; rawSql queries in dashboards/*.json use Postgres syntax
  (double-quoted aliases, `make_interval()` / `INTERVAL '1 day'`,
  `string_to_array()` for multi-value vars, `EXTRACT(EPOCH FROM …)`).
- **Three SD types use Blackbox modules**: HTTP / TCP / ICMP / SSL / GRPC /
  DNS go through Blackbox. The rest (LDAP / Keycloak / DB / Postgres / Redis /
  Mongo / Elasticsearch / Version) are probed by the exporter itself.

## Deployment paths

| Path                | When to use                                    | Where it lives |
|---------------------|------------------------------------------------|----------------|
| docker-compose      | Local dev, small single-host install           | repo root      |
| Helm chart          | K8s / OpenShift, production                    | `deployments/k8s-helm/` |
| AWS (EKS+RDS)       | Public-cloud deploy on AWS                     | `deployments/aws/` |
| GCP (GKE+Cloud SQL) | Public-cloud deploy on GCP                     | `deployments/gcp/` |
| Cloud Run           | Run only admin UI + HTTP-SD (BYO Grafana/Prom) | `deployments/gcp/cloud-run/` |

When you change the exporter code or templates, mirror them into the chart:
copy to `deployments/k8s-helm/dev/monitor-grafana/` (Python files at
chart root, Jinja templates under `web_templates/`). Helm's `templates/`
directory is reserved for K8s manifests.

## AI-agent task runbook

For the most common operation — **adding & validating a new monitored
service** — see `docs/AGENTS.md`. It carries the decision tree, the
REQUIRED_FIELDS matrix, copy-pasteable SQL/HTTP/UI templates per system_type,
the three verification layers (DB → HTTP-SD → Prometheus metric), and the
specific pitfalls that catch agents (chart-mirror contract, Postgres data
volume persistence, metric-naming conventions, intentional SSL negatives).

## Working tree state

The active branch is `develop`; main is `main`. Tests pass with pytest
against `tests/unit`, `tests/dashboards`, and `tests/config` (278 tests).
`pytest tests/live --live` requires `docker compose up -d` and additionally
`COMPOSE_PROFILES=full` for the new `test_bundled_db_probe_is_up`
parametrized cases.

## Personal-instructions overrides

User-level CLAUDE.md (`~/.claude/CLAUDE.md`) carries strict pre-commit rules
(update docs + tests before every commit; verify service responses by content
not status code; complete all work before stopping). Follow them unless a
project-level file here says otherwise.
