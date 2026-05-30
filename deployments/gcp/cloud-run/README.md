# Cloud Run alternative — admin UI + HTTP-SD only

If you already have Grafana and Prometheus running somewhere (Cloud Monitoring,
Grafana Cloud, an existing GKE cluster), you don't need the full Helm chart.
You can run just `monitor-exporter` on Cloud Run and point your existing
Prometheus at its `/sd/*` endpoints.

## What you get

- Admin UI on a Cloud Run URL.
- Prometheus HTTP-SD endpoints reachable from anywhere your Prometheus runs.
- LDAP/Keycloak/Database/Version checks emitted as `/metrics`.

## What you DON'T get

- The full dashboard set (those live with Grafana).
- The Blackbox / SSL exporters — you need them elsewhere if you want HTTP/TCP
  probes.

## Deploy

```bash
PROJECT=$(gcloud config get-value project)
REGION=europe-west3

# 1. Push the image (built once, served from Artifact Registry)
docker build -t \
  "${REGION}-docker.pkg.dev/${PROJECT}/monitor/monitor-exporter:latest" \
  -f ../../../docker/Dockerfile.monitor-exporter ../../..
docker push \
  "${REGION}-docker.pkg.dev/${PROJECT}/monitor/monitor-exporter:latest"

# 2. Apply the service descriptor (edit service.yaml first — image + env)
gcloud run services replace service.yaml \
  --region "$REGION"

# 3. Allow your IP / corporate network to reach the admin UI
gcloud run services add-iam-policy-binding monitor-exporter \
  --region "$REGION" \
  --member=allUsers \
  --role=roles/run.invoker
```

## Database

The exporter needs Postgres. On Cloud Run you have two options:

1. **Cloud SQL via the Cloud SQL connector** — add the connector annotation
   on the service (`run.googleapis.com/cloudsql-instances`) and the exporter
   talks to `/cloudsql/<connection-name>` as a UNIX socket. Cheap, no VPC needed.
2. **Cloud SQL with private IP + a Serverless VPC Connector** — required if
   your DB has only a private IP. Slightly more setup, mandatory for prod.

`service.yaml` documents both — uncomment whichever you use.
