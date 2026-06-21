# monitor-grafana

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Grafana](https://img.shields.io/badge/Grafana-OSS_11.4-orange)](https://grafana.com)
[![Prometheus](https://img.shields.io/badge/Prometheus-2.54-red)](https://prometheus.io)

A **database-driven Grafana + Prometheus** monitoring stack where targets are
managed through a web UI — no YAML files to edit, no stack restarts when adding
or removing probes.

## How It Works

Out of the box, Grafana + Prometheus requires you to edit YAML files and restart
containers every time you add a target. This project replaces that workflow with:

1. **Flask Admin UI** (`:9119/admin`) — add, edit, and delete monitored hosts
   and lab environments through CRUD forms; authentication is delegated to
   Grafana's existing session cookie.
2. **PostgreSQL** — stores the full catalog of monitored systems
   (`monitored_system`), lab environments (`lab`), and probe history.
3. **Prometheus HTTP-SD endpoint** (`/sd/<type>`) — serves the live catalog as
   HTTP service-discovery JSON, refreshed automatically; Prometheus polls it
   every 30 seconds with no reload or restart required.
4. **Grafana** (`:3000`) — dashboards auto-extend via SQL-backed template
   variables and panel repeats; adding a new lab or service type instantly
   appears across all relevant dashboards.
5. **Monitor Exporter** (`:9116`) — custom poller that handles probe types
   Blackbox Exporter does not cover (LDAP, Keycloak, database TCP, version
   endpoints) and exposes the results as Prometheus metrics.

## Architecture

```
                    ┌────────────────────────────────────┐
                    │  Admin UI  (:9119/admin)           │
   browser ◀────────┤  CRUD systems + labs               │
                    │  Auth: Grafana session cookie      │
                    └───────────────┬────────────────────┘
                                    │ writes
                                    ▼
                    ┌────────────────────────────────────┐
                    │  PostgreSQL  (monitoring DB)       │
                    │  monitored_system · lab · history  │
                    └──────────┬─────────────┬───────────┘
                               │ reads       │ reads
                               │             ▼
                               │   ┌──────────────────────┐
                               │   │  Monitor Exporter    │
                               │   │  :9116  (metrics)    │
                               │   │  :9119  (HTTP-SD +   │
                               │   │          Admin UI)   │
                               │   └─────────┬────────────┘
                               │             │ /metrics
                               │             ▼
                               │   ┌──────────────────────┐
                               │   │  Prometheus  :9090   │
                               │   │  scrapes via         │
                               │   │  http_sd_configs     │
                               │   │  → /sd/<type>        │
                               │   └─────────┬────────────┘
                               │             │ queries
                               │             ▼
                               │   ┌──────────────────────┐
                               └──▶│  Grafana  :3000      │
                                   │  dashboards + alerts │
                                   └──────────────────────┘
```

| Service             | Port | Role                                        |
|---------------------|------|---------------------------------------------|
| Grafana             | 3000 | Dashboards, alerting, alert emails          |
| Prometheus          | 9090 | TSDB, 180-day retention                     |
| Blackbox Exporter   | 9115 | HTTP / TCP / ICMP / DNS probes              |
| Monitor Exporter    | 9116 | LDAP / Keycloak / DB / Version metrics      |
| SSL Exporter        | 9117 | TLS certificate metadata & expiry           |
| Admin UI + HTTP-SD  | 9119 | System & lab CRUD, Prometheus SD endpoints |
| PostgreSQL          | 5433 | Service catalog + probe history (host port) |

## Supported Probe Types

| Type            | Description                                        |
|-----------------|----------------------------------------------------|
| HTTP / HTTPS    | Availability, status code, response time           |
| TCP             | Port reachability                                  |
| ICMP            | Host ping via Blackbox                             |
| SSL             | Certificate validity and days-to-expiry            |
| DNS             | Name resolution checks                             |
| LDAP            | Directory bind and query checks                    |
| Keycloak        | Realm availability (OIDC well-known endpoint)      |
| DATABASE        | MySQL / MariaDB TCP connectivity                   |
| POSTGRES        | PostgreSQL TCP connectivity                        |
| REDIS           | Redis TCP connectivity                             |
| MONGODB         | MongoDB TCP connectivity                           |
| ELASTICSEARCH   | Elasticsearch cluster health                       |
| gRPC            | gRPC health protocol checks                        |
| VERSION         | Application version / OpenAPI endpoint checks      |

## Quick Start

Requires Docker and Docker Compose.

```bash
git clone https://github.com/Dmitrii-Volokitin-Job/monitor-grafana.git
cd monitor-grafana
cp .env.example .env          # set POSTGRES_PASSWORD, GF_SECURITY_ADMIN_PASSWORD, etc.
docker compose up -d          # starts Grafana, Prometheus, Blackbox, exporter, Postgres
```

On first start, the database is seeded with two demo labs and 18 example
systems covering every probe type. Probes hit real public services where
possible (httpbin.org, 1.1.1.1, ldap.forumsys.com, grpcb.in, etc.) so
dashboards show live data immediately.

```bash
# Verify the discovery chain end-to-end:
curl -s http://localhost:9119/sd/http | jq '.[].labels.system_id'
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[0]'
```

**Full profile** — also starts bundled Postgres, MySQL, Redis, MongoDB, and
Elasticsearch containers so every DB-style dashboard panel shows real UP data:

```bash
COMPOSE_PROFILES=full docker compose up -d
```

### Access

| URL                                | Description                       |
|------------------------------------|-----------------------------------|
| http://localhost:3000              | Grafana (default: admin/admin)    |
| http://localhost:9119/admin        | Admin UI (Grafana session required)|
| http://localhost:9090              | Prometheus                        |

## Adding a New Monitored Service

1. Log in to Grafana at `http://localhost:3000`.
2. Open the Admin UI at `http://localhost:9119/admin/`.
3. Click **+ New system**, choose a probe type from the dropdown, fill the
   type-specific form, and save.
4. Within ~30 seconds the system appears in `/sd/<type>`, Prometheus scrapes
   it, and dashboards reflect the new target automatically.

For scripted or agent-driven additions (SQL INSERT or HTTP POST), see
[docs/AGENTS.md](docs/AGENTS.md) for the full field matrix and a three-step
verification recipe (DB row → HTTP-SD payload → Prometheus metric).

## Deployment

| Target                         | Path                           |
|--------------------------------|--------------------------------|
| Local dev (Docker Compose)     | `docker compose up -d`         |
| Kubernetes / OpenShift         | `deployments/k8s-helm/`        |
| AWS (EKS + RDS)                | `deployments/aws/`             |
| GCP (GKE + Cloud SQL)          | `deployments/gcp/`             |

Each deployment folder contains its own README. The Helm chart is the canonical
artifact for any Kubernetes-style runtime; the cloud folders wrap it with
platform-specific infrastructure (Terraform + values overlays).

## Configuration

All secrets are supplied via environment variables — none are committed to the
repository. Copy `.env.example` to `.env` and set:

| Variable                    | Description                                      |
|-----------------------------|--------------------------------------------------|
| `POSTGRES_PASSWORD`         | PostgreSQL password                              |
| `GF_SECURITY_ADMIN_PASSWORD`| Grafana admin password                           |
| `ADMIN_UI_SECRET_KEY`       | Flask session signing key                        |
| `GRAFANA_PUBLIC_URL`        | Public Grafana URL (used in alert email links)   |
| `SMTP_HOST`, `SMTP_PORT`    | SMTP server for Grafana alert emails (optional)  |

See `.env.example` for the full list and defaults.

## Stack

- **Python · Flask · SQLAlchemy** — Admin UI and monitor exporter
- **PostgreSQL 16** — Service catalog and probe history
- **Prometheus 2.54** — Metrics collection, 180-day TSDB retention
- **Blackbox Exporter 0.25** — HTTP / TCP / ICMP / DNS probes
- **SSL Exporter 2.4** — TLS certificate monitoring
- **Grafana OSS 11.4** — Dashboards and alerting
- **Grafana Image Renderer 3.11** — Dashboard screenshots in alert emails
- **Docker Compose** — Single-command local deployment

## Testing

```bash
pip install -r requirements-test.txt
pytest tests/unit          # fast, mocked, no infrastructure required
pytest tests/dashboards    # JSON schema and PromQL syntax validators
pytest tests/live --live   # requires docker compose up
```

## Documentation

- [docs/runbook.md](docs/runbook.md) — Alert runbook and Admin UI walkthrough
- [docs/AGENTS.md](docs/AGENTS.md) — SQL/HTTP methods for scripted target management
- [docs/admin-guide-dashboards.html](docs/admin-guide-dashboards.html) — Dashboard reference
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development workflow and contribution guide
- [CHANGELOG.md](CHANGELOG.md) — Release history

## License

Apache 2.0 — see [LICENSE](LICENSE).
