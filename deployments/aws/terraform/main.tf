# Minimal AWS infra for the Monitor monitoring stack.
#
# This is a starting point. It provisions:
#   - VPC (3 AZs, public + private subnets)
#   - EKS cluster (single node group on private subnets)
#   - RDS MariaDB (single AZ; flip to multi_az = true for prod)
#   - ECR repository for the exporter image
#   - Secrets Manager entries for the four token-style secrets
#
# Things you'll likely tune before the first apply:
#   - aws_region, environment_name
#   - instance_type / desired_size on the node group
#   - rds.instance_class, rds.allocated_storage, rds.engine_version
#   - tags / cost-allocation tags
#
# After apply:
#   kubeconfig:  aws eks update-kubeconfig --region $REGION --name $CLUSTER_NAME
#   then:        helm upgrade --install … -f ../values-aws.yaml

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region"       { default = "eu-central-1" }
variable "environment_name" { default = "monitor" }
variable "vpc_cidr"         { default = "10.42.0.0/16" }

locals {
  azs          = ["${var.aws_region}a", "${var.aws_region}b", "${var.aws_region}c"]
  cluster_name = "${var.environment_name}-eks"
  common_tags  = { Project = "monitor-grafana", ManagedBy = "terraform" }
}

# --- Networking ----------------------------------------------------------------

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "${var.environment_name}-vpc"
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 10)]

  enable_nat_gateway   = true
  single_nat_gateway   = true   # cost-optimised; switch off for prod HA
  enable_dns_hostnames = true

  tags = local.common_tags
}

# --- EKS -----------------------------------------------------------------------

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.20"

  cluster_name    = local.cluster_name
  cluster_version = "1.30"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.large"]
      min_size       = 1
      desired_size   = 2
      max_size       = 4
    }
  }

  tags = local.common_tags
}

# --- RDS Postgres --------------------------------------------------------------

resource "aws_db_subnet_group" "postgres" {
  name       = "${var.environment_name}-postgres"
  subnet_ids = module.vpc.private_subnets
  tags       = local.common_tags
}

resource "aws_security_group" "postgres" {
  name        = "${var.environment_name}-postgres-sg"
  description = "Allow Postgres from EKS pods"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    cidr_blocks     = [var.vpc_cidr]
    description     = "Postgres from VPC"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = local.common_tags
}

resource "random_password" "postgres" {
  length  = 24
  special = false
}

resource "aws_db_instance" "postgres" {
  identifier              = "${var.environment_name}-postgres"
  engine                  = "postgres"
  engine_version          = "16.3"
  instance_class          = "db.t3.medium"
  allocated_storage       = 50
  storage_type            = "gp3"
  db_name                 = "monitoring"
  username                = "monitoring"
  password                = random_password.postgres.result
  db_subnet_group_name    = aws_db_subnet_group.postgres.name
  vpc_security_group_ids  = [aws_security_group.postgres.id]
  multi_az                = false   # flip to true for prod
  backup_retention_period = 7
  skip_final_snapshot     = true    # set false in prod
  publicly_accessible     = false
  tags                    = local.common_tags
}

# --- ECR -----------------------------------------------------------------------

resource "aws_ecr_repository" "exporter" {
  name                 = "monitor-exporter"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = local.common_tags
}

# --- Secrets Manager -----------------------------------------------------------

resource "aws_secretsmanager_secret" "tokens" {
  name = "${var.environment_name}/tokens"
  tags = local.common_tags
}
resource "aws_secretsmanager_secret_version" "tokens" {
  secret_id = aws_secretsmanager_secret.tokens.id
  secret_string = jsonencode({
    gitlab_token          = "PUT_GLPAT_HERE"
    gitlab_trigger_token  = "PUT_GLPTT_HERE"
    sonar_token           = "PUT_SQU_HERE"
    trigger_shared_secret = "PUT_RANDOM_HERE"
    admin_ui_secret_key   = "PUT_RANDOM_HERE"
  })
  lifecycle { ignore_changes = [secret_string] }
}

resource "aws_secretsmanager_secret" "postgres" {
  name = "${var.environment_name}/postgres"
  tags = local.common_tags
}
resource "aws_secretsmanager_secret_version" "postgres" {
  secret_id = aws_secretsmanager_secret.postgres.id
  secret_string = jsonencode({
    host     = aws_db_instance.postgres.address
    port     = aws_db_instance.postgres.port
    user     = aws_db_instance.postgres.username
    password = random_password.postgres.result
    database = "monitoring"
  })
}

# --- Outputs -------------------------------------------------------------------

output "cluster_name"      { value = module.eks.cluster_name }
output "cluster_endpoint"  { value = module.eks.cluster_endpoint }
output "ecr_repository_url"{ value = aws_ecr_repository.exporter.repository_url }
output "postgres_endpoint" { value = aws_db_instance.postgres.address }
output "kubeconfig_cmd" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
