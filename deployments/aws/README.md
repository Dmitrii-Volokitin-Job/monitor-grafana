# AWS deployment

The same Helm chart at `deployments/k8s-helm/dev/monitor-grafana/` works on EKS without modification. This folder collects the AWS-specific bits you wrap around it.

## Recommended topology

| AWS service | Used for | Replaces |
|---|---|---|
| **EKS** (or Fargate-only) | Run the Helm chart workloads | OpenShift |
| **RDS Postgres** (Multi-AZ) | `monitoring` database | self-hosted Postgres |
| **ECR** | `monitor-exporter` image registry | `app.example.com/monitor-exporter:*` |
| **ALB Ingress Controller** | Public Grafana + admin UI ingress | OpenShift Route |
| **AWS Secrets Manager** | `monitor-tokens`, `grafana-secret`, DB password | OpenShift Secret |
| **Route 53** | DNS for Grafana hostname | internal DNS |
| **ACM** | TLS cert for Grafana | wildcard `*.app.example.com` |

## Bring-up cheat sheet

```bash
# 1. Build & push the exporter image
aws ecr get-login-password --region eu-central-1 | docker login --username AWS \
  --password-stdin "$ACCOUNT.dkr.ecr.eu-central-1.amazonaws.com"
docker build -t monitor-exporter -f docker/Dockerfile.monitor-exporter .
docker tag monitor-exporter "$ACCOUNT.dkr.ecr.eu-central-1.amazonaws.com/monitor-exporter:latest"
docker push "$ACCOUNT.dkr.ecr.eu-central-1.amazonaws.com/monitor-exporter:latest"

# 2. Apply the EKS infra (see terraform/ in this folder)
cd terraform && terraform init && terraform apply

# 3. Install the chart with an AWS-specific values overlay
helm upgrade --install monitor ../../k8s-helm/dev/monitor-grafana \
  -f values-aws.yaml \
  --namespace monitor --create-namespace
```

## What's in this folder

- `terraform/` — minimal infra: VPC, EKS cluster, RDS Postgres instance, ECR repo,
  Secrets Manager entries. Read it as a starting point, not a copy-paste solution
  (region, sizes, tags are placeholders).
- `values-aws.yaml` — overlay for the Helm chart. Points `postgres.host` at the RDS
  endpoint, references the secrets created by Secrets Manager, wires the ALB
  ingress class.
- `secrets-manager.md` — how to populate the secrets the chart reads.

## What is intentionally NOT here

- IAM roles for service accounts (IRSA) — depends on your org's policy boundary.
  Use `eksctl create iamserviceaccount` per the AWS docs.
- Backups for RDS — RDS automated backups + a snapshot retention policy that
  matches the Galera cluster's RPO is straightforward but org-specific.
- VPC peering with on-prem labs — needed if you want to keep
  probing those endpoints from the AWS-hosted monitor. Use Direct Connect or
  a Site-to-Site VPN; configuration lives in your network team's repo.
