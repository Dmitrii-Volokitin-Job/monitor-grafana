# monitor-grafana

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)](#testing)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Grafana](https://img.shields.io/badge/Grafana-OSS_11.4-orange)](https://grafana.com)
[![Prometheus](https://img.shields.io/badge/Prometheus-2.54-red)](https://prometheus.io)

A **database-driven monitoring stack** built on Grafana + Prometheus. Add HTTP
probes, TCP/ICMP/SSL/LDAP/Keycloak/Database/Postgres/Redis/MongoDB/Elasticsearch
/gRPC/DNS/Version checks **through a web UI** instead of editing YAML; the
changes flow into Prometheus within 30 seconds via HTTP service discovery.

## Why

Out of the box, Grafana + Prometheus needs you to edit YAML files and restart
containers every time you add a target. This project replaces that with:

- A **Postgres-backed catalog** of monitored systems (`monitored_system` table)
  and labs (`lab` table).
- A **Flask admin UI** on port 9119 with CRUD pages for both, login delegated
  to Grafana's existing session.
- A **Prometheus HTTP-SD endpoint** (`/sd/<type>`) that serves the same catalog
  to Prometheus — no `/-/reload`, no shared volumes, no pod restarts.
- **Dashboards that auto-extend** when you add a lab or service, via Grafana
  panel repeats driven by SQL-backed template variables.

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │  Admin UI  (:9119/admin)            │
   browser ◀────────┤  CRUD systems + labs                │
                    │  Auth: Grafana session cookie       │
                    └────────────────┬────────────────────┘
                                     │ writes
                                     ▼
                    ┌─────────────────────────────────────┐
                    │  Postgres  (monitoring)             │
                    │  monitored_system, lab, history     │
                    └────────────┬────────────┬───────────┘
                                 │ reads      │ reads
                                 │            ▼
                                 │   ┌────────────────────┐
                                 │   │  monitor-     │
                                 │   │  exporter (:9116)  │
                                 │   │  LDAP/Keycloak/DB/ │
                                 │   │  Version checks    │
                                 │   └─────────┬──────────┘
                                 │             │ /metrics
                                 │             ▼
                                 │   ┌────────────────────┐
                                 │   │  Prometheus :9090  │
                                 │   │  scrapes via       │
                                 │   │  http_sd_configs   │
                                 │   │  → /sd/<type>      │
                                 │   └─────────┬──────────┘
                                 │             │ queries
                                 │             ▼
                                 │   ┌────────────────────┐
                                 └──▶│  Grafana :3000     │
                                     │  dashboards +      │
                                     │  alerts            │
                                     └────────────────────┘
```

| Service              | Port  | Role                                       |
|----------------------|-------|--------------------------------------------|
| Grafana              | 3000  | Dashboards, alerting                       |
| Prometheus           | 9090  | TSDB, 180-day retention                    |
| Blackbox Exporter    | 9115  | HTTP / TCP / ICMP probes                   |
| Monitor Exporter| 9116  | LDAP / Keycloak / DB / Version metrics     |
| ssl_exporter         | 9117  | TLS certificate metadata                   |
| **Admin UI + HTTP-SD**| **9119**| **System & lab CRUD, Prometheus SD**     |
| Postgres             | 5432  | History + service catalog                  |

## Quick start

Requires Docker + Docker Compose.

```bash
git clone https://github.com/your-org/monitor-grafana.git
cd monitor-grafana
cp .env.example .env             # adjust if you want non-default ports/passwords
docker compose up -d             # lean default — Grafana/Prom/Blackbox/exporter

# OR: bring up the FULL profile with bundled real Postgres/MySQL/Redis/Mongo/ES
# target containers so every DB-style dashboard panel shows real UP data:
COMPOSE_PROFILES=full docker compose up -d

# 1. Grafana UI    → http://localhost:3000  (login: admin / admin)
# 2. Admin UI      → http://localhost:9119/admin   (Grafana session required)
# 3. Prometheus    → http://localhost:9090
# 4. Demo data: 2 labs × 9 system types = 18 example systems are seeded on
#    first start. Probes hit REAL public services where possible
#    (httpbin.org, 1.1.1.1, ldap.forumsys.com, www.keycloak.org, grpcb.in,
#    petstore.swagger.io, github.com, play.grafana.org) plus two intentional
#    SSL negatives (expired.badssl.com, self-signed.badssl.com) so the SSL
#    alerting can be observed firing. With COMPOSE_PROFILES=full, the DB-style
#    probes additionally hit locally-bundled real containers — every dashboard
#    panel then has live data.

# Confirm the chain works end-to-end:
curl -s http://localhost:9119/sd/http | jq '.[].labels.system_id'
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[0]'
```

## Adding your own service

1. Log into Grafana (`admin/admin` by default — change it).
2. Open `http://localhost:9119/admin/`.
3. Click **+ New system**, pick a type (HTTP / TCP / ICMP / SSL / LDAP /
   KEYCLOAK / DATABASE / POSTGRES / REDIS / MONGODB / ELASTICSEARCH / GRPC /
   DNS / VERSION).
4. Fill the type-specific form, save.
5. Within ~30 seconds your service appears in `/sd/<type>`, Prometheus picks
   it up, the exporter starts probing, and dashboards reflect it.

**Doing this from a script or AI agent?** See `docs/AGENTS.md` for the
SQL-INSERT and HTTP-POST methods, the REQUIRED_FIELDS matrix per system_type,
copy-pasteable templates, and a three-layer verification recipe
(DB row → HTTP-SD payload → Prometheus metric value).

For labs, go to **Labs → + New lab**. New labs show up in every dashboard's
lab dropdown automatically (SQL-backed template variables).

## Deployment

| Target                          | Path                                                |
|---------------------------------|-----------------------------------------------------|
| **Local dev (Docker Compose)**  | `docker compose up -d` from repo root               |
| **Kubernetes / OpenShift**      | Helm chart at `deployments/k8s-helm/`               |
| **AWS (EKS + RDS)**             | Starter: `deployments/aws/`                         |
| **GCP (GKE + Cloud SQL)**       | Starter: `deployments/gcp/`                         |

Each deployment folder has its own README with the specifics. The Helm chart
itself is the canonical artefact for any Kubernetes-style runtime; cloud
folders only wrap it with platform-specific infra (Terraform / values overlays).

## Configuration

All runtime secrets are read from environment variables — none are committed:

- `GRAFANA_INTERNAL_URL`, `GRAFANA_PUBLIC_URL` — where the admin UI looks for
  Grafana's `/api/user` to validate sessions
- `ADMIN_UI_SECRET_KEY` — Flask session signing key
- `POSTGRES_PASSWORD` — overrides `postgres.password` from `config.yml`
  pollers
- SMTP creds — for Grafana alert emails

See `.env.example` for the full list.

## Documentation

- [docs/runbook.md](docs/runbook.md) — what to do when each alert fires;
  admin UI walkthrough
- [docs/SECURITY.md](docs/SECURITY.md) — reporting vulnerabilities + how
  secrets are handled
- [docs/admin-guide-dashboards.html](docs/admin-guide-dashboards.html) — every
  dashboard explained, panel by panel
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to develop / submit changes
- [CHANGELOG.md](CHANGELOG.md) — release history

## Testing

```bash
pip install -r requirements-test.txt
pytest tests/unit              # fast, mocked, no infra
pytest tests/dashboards        # JSON schema + PromQL syntax validators
pytest tests/live --live       # requires docker compose up
```

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). For bugs or feature
ideas, please [open an issue](https://github.com/your-org/monitor-grafana/issues).

## License

Apache 2.0 — see [LICENSE](LICENSE).
