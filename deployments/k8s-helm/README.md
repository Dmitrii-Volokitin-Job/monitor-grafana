# Kubernetes / OpenShift deployment (Helm)

This is the **canonical artefact** for any Kubernetes-style runtime. Cloud
overlays under `../aws/` and `../gcp/` only wrap this chart with
platform-specific infra (Terraform, values overrides).

## Layout

| Path | What |
|---|---|
| `dev/monitor-grafana/` | The Helm chart itself. `Chart.yaml`, `values.yaml`, `templates/`, plus mirrored Python sources + dashboards + web templates that get baked into ConfigMaps. |
| `helm-values/`        | Per-environment values overrides (e.g. `monitor/dev/monitor-grafana/values.yaml`). |
| `gitops-configs/`     | Argo CD / Flux Application manifests, if you wire GitOps. |

## Quick start

```bash
# install / upgrade against your current kube-context
helm upgrade --install monitor dev/monitor-grafana \
  --namespace monitor --create-namespace \
  --set dbSecrets.postgresPassword=$(openssl rand -hex 16)

# or with an env overlay
helm upgrade --install monitor dev/monitor-grafana \
  -f helm-values/monitor/dev/monitor-grafana/values.yaml \
  --namespace monitor --create-namespace
```

## What gets created

- `postgres` Deployment + Service (internal metadata DB; swap to RDS / Cloud SQL via `postgres.host`).
- `grafana` Deployment + Service + provisioning ConfigMaps (datasources, dashboards, alert rules).
- `monitor-exporter` Deployment (LDAP/Keycloak/DB/Version checks + admin UI + Prometheus HTTP-SD on port 9119).
- `prometheus` Deployment + Service (180-day TSDB retention).
- `blackbox-exporter`, `ssl-exporter` Deployments.

## Cross-deployment sync

The chart bakes the exporter Python, the dashboard JSON, and the alert-rule
YAML into ConfigMaps at render time, so whenever you edit any of those, you
must mirror them into the chart directory:

```bash
HELM_CHART=deployments/k8s-helm/dev/monitor-grafana

cp monitor_exporter/*.py    "$HELM_CHART/"
cp monitor_exporter/config.yml "$HELM_CHART/"
cp dashboards/*.json        "$HELM_CHART/dashboards/"
cp config/alert_rules/*.yml "$HELM_CHART/alert_rules/"
```

> The duplication is a deliberate trade-off: Helm has no clean built-in way to
> pull files from outside the chart directory. The mirror step is part of the
> release workflow — verify with `diff -r monitor_exporter $HELM_CHART` before
> publishing the chart.

## When to use

- Anything beyond local dev: production, staging, multi-node, GitOps.

For a single-host setup use `../docker/` instead.
