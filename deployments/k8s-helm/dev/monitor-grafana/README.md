# monitor-grafana Helm chart

The canonical artefact for running the stack on Kubernetes / OpenShift.
Cloud overlays (`deployments/aws/values-aws.yaml`, `deployments/gcp/values-gcp.yaml`)
wrap this chart with platform-specific values — they don't fork it.

## Quick install

```bash
helm upgrade --install monitor . \
  -f values.yaml \
  --namespace monitoring --create-namespace \
  --set dbSecrets.postgresPassword=$(openssl rand -hex 16) \
  --set grafana.adminPassword=$(openssl rand -hex 16)
```

For a demo cluster where every dashboard panel should show real UP data, also
pass `--set demoTargets.enabled=true` (starts five extra Postgres/MySQL/Redis/
MongoDB/Elasticsearch pods that the seed's DB-style probes point at).

## What the chart renders

| Component | Templates | Purpose |
|---|---|---|
| **Postgres** | `postgres.yaml`, `monitor-db-init.yaml` | In-cluster metadata DB + init SQL ConfigMap. Skipped when `postgres.deployInCluster=false` (use managed RDS / Cloud SQL instead). |
| **Prometheus** | `prometheus-*.yaml` | Scrapes blackbox / SSL / monitor-exporter targets via HTTP-SD on port 9119. |
| **Blackbox exporter** | `blackbox-*.yaml` | HTTP / TCP / ICMP / SSL / gRPC / DNS probes. |
| **SSL exporter** (ribbybibby) | `ssl-exporter-*.yaml` | Cert chain validation, `ssl_cert_not_after` metric. |
| **monitor-exporter** | `monitor-exporter-*.yaml` | Python service: admin UI (`:9119/admin`), HTTP-SD (`:9119/sd/<type>`), `/metrics` (`:9116`), LDAP/Keycloak/DB/version probes. Readiness probe on `/sd/healthz`. |
| **Grafana** | `grafana-*.yaml` | Dashboards + datasource provisioning, embedded admin UI iframe. |
| **smtp-to-graph** (optional) | `smtp-to-graph-deployment.yaml` | SMTP→Microsoft Graph sidecar for tenants that egress mail through Graph. |
| **Demo target containers** | `demo-targets.yaml` | Five Deployments (Postgres/MySQL/Redis/Mongo/ES) gated by `demoTargets.enabled=true`. |

## Top-level `values.yaml` keys

| Key | Default | Notes |
|---|---|---|
| `namespace` | `monitoring` | Namespace every resource lands in. |
| `prometheus.*` | — | Image tag, retention (7d default), resources, PVC size. |
| `blackboxExporter.*`, `sslExporter.*`, `monitorExporter.*`, `grafana.*` | — | Per-component image / resources / port overrides. |
| `postgres.deployInCluster` | `true` | `false` skips the in-cluster Postgres and expects `postgres.host` to point at managed RDS / Cloud SQL. |
| `postgres.password` | `""` | Never set in plaintext — pass via `--set` from a Secret manager. |
| `dbSecrets.postgresPassword` | `""` | Rendered into `monitor-db-secrets` Secret; empty → Secret skipped. |
| `grafana.adminPassword` | `""` | Rendered into `grafana-admin-secret`; empty → Grafana defaults to `admin/admin` and forces a change on first login. |
| `demoTargets.enabled` | `false` | `true` adds 5 bundled DB-style demo containers (see Demo targets below). |
| `tokens.{gitlab,sonar,…}` | `""` | Optional CI tokens rendered into `monitor-tokens` Secret. Empty → Secret skipped. |
| `routes.enabled` | `true` (OpenShift) | Disable when using ALB / GCE ingress instead. |
| `ingress.enabled` | `false` | Enable + override `ingress.className` when on EKS / GKE. |
| `hostAliases` | `[]` | Inject /etc/hosts entries into the exporter pod (for probes against hosts the cluster DNS can't resolve). |
| `smtp.*` / `smtpToGraph.*` / `graphOAuth.*` | — | Mail egress. Only one of `smtp.*` (direct) or `smtpToGraph.*` (via Microsoft Graph sidecar) needed. |

## Demo target containers (`demoTargets.enabled=true`)

Renders 5 Deployments + 5 ClusterIP Services (Postgres 16, MySQL 8, Redis 7,
MongoDB 7, Elasticsearch 8.13). The seed's `demo-{a,b}-{postgres,redis,
mongo,es,mariadb}` rows point at these hostnames (`demo-postgres-target`,
`demo-mysql-target`, etc.) so every dashboard panel shows real UP data on
first boot. Mirrors the `COMPOSE_PROFILES=full` profile in docker-compose.
Default `false` to keep production installs lean.

Containers run without auth on the cluster's internal network — never
expose via Ingress.

## Sync contract with docker-compose

This chart embeds copies of `admin_ui.py`, `exporter.py`, `db.py`,
`datasource_sync.py`, `sd_endpoints.py`, `smtp_to_graph.py`, `config.yml`,
and the dashboards JSON at the chart root. Same content lives at
`monitor_exporter/*`, `dashboards/*` at the repo root — the chart's `values`
ConfigMap re-mounts them inside Kubernetes.

**Editing the Python or dashboards in `monitor_exporter/` or `dashboards/`?
Mirror the change here.** There is no auto-sync. The same rule applies to
SQL changes in `docker/init-db/*.sql` → `templates/monitor-db-init.yaml`.

## Common values.yaml overrides per deploy path

| Path | Recommended overrides |
|---|---|
| AWS EKS | `routes.enabled=false`, `ingress.enabled=true`, `ingress.className=alb`, `postgres.deployInCluster=false`, `postgres.host=<RDS endpoint>` |
| GCP GKE | `routes.enabled=false`, `ingress.enabled=true`, `ingress.className=gce`, `postgres.deployInCluster=false`, `postgres.host=<Cloud SQL private IP>` |
| OpenShift | `routes.enabled=true` (default), `ingress.enabled=false` |
| Local kind / minikube demo | `demoTargets.enabled=true`, `postgres.deployInCluster=true` |

## Related

- Repo root `README.md` — user-facing intro + docker-compose quick start.
- `deployments/k8s-helm/README.md` — broader chart-vs-cloud-overlay walkthrough.
- `deployments/k8s-helm/helm-values/` — example overlay files per environment.
- `deployments/k8s-helm/gitops-configs/` — ArgoCD / Flux manifests that point at this chart.
- `CLAUDE.md` & `docs/AGENTS.md` — architecture and "how to add a service" workflows.
