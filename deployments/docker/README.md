# Docker Compose deployment

This directory is an ergonomic wrapper. The canonical Compose file lives at
the repo root; everything here is a symlink so you can `cd deployments/docker
&& docker compose up -d` instead of running from the project root.

## Quick start

```bash
cd deployments/docker
docker compose up -d
```

Then open:

| Service | URL | Notes |
|---|---|---|
| Grafana | http://localhost:3000 | login `admin` / `admin` |
| Admin UI | http://localhost:9119/admin/ | requires a logged-in Grafana session |
| Prometheus | http://localhost:9090 | |
| Exporter `/metrics` | http://localhost:9116/metrics | |
| Postgres | `localhost:5433` | db `monitoring`, user `monitoring` |

Override host ports if they collide with other stacks:

```bash
GRAFANA_HOST_PORT=3030 PROMETHEUS_HOST_PORT=9091 \
LOKI_HOST_PORT=3110   POSTGRES_HOST_PORT=5434 \
  docker compose up -d
```

See `../../.env.example` for the full env-var list.

## When to use

- Local development.
- Single-host on-prem installs.
- Demos / proofs-of-concept where Kubernetes is overkill.

For Kubernetes deployments use the Helm chart at `../k8s-helm/`. For managed
cloud see `../aws/` (EKS + RDS) or `../gcp/` (GKE + Cloud SQL).
