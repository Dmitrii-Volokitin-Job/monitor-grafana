# GCP deployment

The Helm chart at `deployments/k8s-helm/dev/monitor-grafana/` works on
GKE without modification. This folder collects the GCP-specific bits you wrap
around it.

## Recommended topology

| GCP service                  | Used for                                     |
|------------------------------|----------------------------------------------|
| **GKE Autopilot**            | Run the Helm chart workloads                 |
| **Cloud SQL for Postgres**   | `monitoring` catalog + history               |
| **Artifact Registry**        | `monitor-exporter` image registry       |
| **Cloud Load Balancing**     | Public Grafana + admin UI ingress            |
| **Secret Manager**           | `monitor-tokens`, datasource passwords  |
| **Cloud DNS**                | DNS for Grafana hostname                     |
| **Managed Certificates**     | TLS for Grafana                              |

## Bring-up cheat sheet

```bash
# 0. Authenticate
gcloud auth login
gcloud auth configure-docker europe-west3-docker.pkg.dev

# 1. Provision infra
cd terraform
terraform init
terraform apply

# 2. Configure kubectl
gcloud container clusters get-credentials monitor-gke \
  --region europe-west3

# 3. Build & push the exporter image
PROJECT=$(gcloud config get-value project)
docker build -t \
  "europe-west3-docker.pkg.dev/$PROJECT/monitor/monitor-exporter:latest" \
  -f docker/Dockerfile.monitor-exporter .
docker push \
  "europe-west3-docker.pkg.dev/$PROJECT/monitor/monitor-exporter:latest"

# 4. Install the chart with the GCP overlay
helm upgrade --install monitor \
  ../k8s-helm/dev/monitor-grafana \
  -f values-gcp.yaml \
  --namespace monitor --create-namespace
```

## What's in this folder

- `terraform/` — minimal infra: GKE cluster, Cloud SQL for MySQL,
  Artifact Registry, Secret Manager entries. Read as a starting point —
  region, machine types, and tier are placeholders.
- `values-gcp.yaml` — overlay for the Helm chart. Points the exporter at the
  Cloud SQL private IP, references Secret Manager-backed secrets via
  `secretRef`, wires the GCE ingress class.
- `cloud-run/` — alternative path that runs only the exporter + admin UI on
  Cloud Run (no GKE). Useful when you already have Grafana / Prometheus
  elsewhere and just want the admin UI + HTTP-SD service.

## What is intentionally NOT here

- Workload Identity binding setup — depends on your org's IAM policy.
  Follow the [GKE Workload Identity guide](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity).
- Cloud SQL Auth Proxy sidecar — fine to skip if your GKE cluster has
  Private Service Access to Cloud SQL.
- Backup retention configuration — Cloud SQL automated backups are sensible
  defaults; tune to your RPO.
- Cross-VPC peering with on-prem — if you need to probe internal targets
  from GCP, set up a Cloud VPN or Cloud Interconnect.

## Cloud Run alternative (no GKE)

If you don't run Kubernetes, you can host just the admin UI + Prometheus
HTTP-SD service on Cloud Run and use Cloud Monitoring as your Prometheus
backend. See `cloud-run/README.md`.
