# Minimal GCP infra for the Monitor monitoring stack.
#
# This is a starting point. It provisions:
#   - VPC with /16 subnet + secondary ranges for pods + services
#   - GKE Autopilot cluster (regional)
#   - Cloud SQL for Postgres (private IP, single-zone — flip to REGIONAL for prod)
#   - Artifact Registry repository for the exporter image
#   - Secret Manager entries for the tokens / DB passwords
#
# Things you'll likely tune before the first apply:
#   - project_id, region
#   - cloud_sql.tier, cloud_sql.availability_type
#   - tags / labels for cost allocation
#
# After apply:
#   gcloud container clusters get-credentials $(terraform output -raw cluster_name) \
#     --region $(terraform output -raw region)
#   helm upgrade --install ... -f ../values-gcp.yaml

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" { type = string }
variable "region"     { default = "europe-west3" }
variable "name"       { default = "monitor" }

locals {
  labels = { project = "monitor-grafana", managed-by = "terraform" }
}

# --- VPC -----------------------------------------------------------------------

resource "google_compute_network" "vpc" {
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "${var.name}-subnet"
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = "10.42.0.0/20"

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.43.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.44.0.0/20"
  }
}

# --- Private Service Connection for Cloud SQL ----------------------------------

resource "google_compute_global_address" "private_ip_range" {
  name          = "${var.name}-cloud-sql-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "vpc_to_sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# --- GKE Autopilot -------------------------------------------------------------

resource "google_container_cluster" "gke" {
  name     = "${var.name}-gke"
  location = var.region
  network  = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  enable_autopilot = true

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Allow Autopilot to manage release channel; pin if you want explicit control.
  release_channel { channel = "REGULAR" }

  deletion_protection = false
}

# --- Cloud SQL for Postgres ----------------------------------------------------

resource "random_password" "postgres" {
  length  = 24
  special = false
}

resource "google_sql_database_instance" "postgres" {
  name             = "${var.name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = "db-custom-2-7680"    # ~ 2 vCPU / 7.5 GB; tune down for cheap dev
    availability_type = "ZONAL"               # REGIONAL for HA
    disk_size         = 50
    disk_type         = "PD_SSD"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
    backup_configuration {
      enabled = true
    }
    user_labels = local.labels
  }

  deletion_protection = false
  depends_on = [google_service_networking_connection.vpc_to_sql]
}

resource "google_sql_database" "monitoring" {
  name     = "monitoring"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "monitoring" {
  name     = "monitoring"
  instance = google_sql_database_instance.postgres.name
  password = random_password.postgres.result
}

# --- Artifact Registry ---------------------------------------------------------

resource "google_artifact_registry_repository" "exporter" {
  location      = var.region
  repository_id = "monitor"
  format        = "DOCKER"
  labels        = local.labels
}

# --- Secret Manager ------------------------------------------------------------

resource "google_secret_manager_secret" "postgres_password" {
  secret_id = "${var.name}-postgres-password"
  replication { auto {} }
}

resource "google_secret_manager_secret_version" "postgres_password" {
  secret      = google_secret_manager_secret.postgres_password.id
  secret_data = random_password.postgres.result
}

resource "google_secret_manager_secret" "tokens" {
  for_each = toset([
    "gitlab-token",
    "gitlab-trigger-token",
    "sonar-token",
    "trigger-shared-secret",
    "admin-ui-secret-key",
  ])
  secret_id = "${var.name}-${each.key}"
  replication { auto {} }
}

# --- Outputs -------------------------------------------------------------------

output "region"            { value = var.region }
output "cluster_name"      { value = google_container_cluster.gke.name }
output "postgres_host"     { value = google_sql_database_instance.postgres.private_ip_address }
output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.exporter.repository_id}"
}
output "kubeconfig_cmd" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.gke.name} --region ${var.region}"
}
