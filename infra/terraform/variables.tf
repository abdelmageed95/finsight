# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Project name — prefixes every resource."
  type        = string
  default     = "finsight"
}

variable "environment" {
  description = "Deployment environment (prod, staging, …)."
  type        = string
  default     = "prod"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDRs for the public subnets (ALB, NAT, Chroma EC2). One per AZ."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDRs for the private subnets (ECS tasks, RDS, Redis). One per AZ."
  type        = list(string)
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
}

# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

variable "db_name" {
  description = "Postgres database name."
  type        = string
  default     = "finsight"
}

variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "finsight"
}

variable "db_password" {
  description = "Postgres master password. Set via terraform.tfvars or TF_VAR_db_password — never commit it."
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class. Portfolio-grade default."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "RDS storage in GB (gp3, autoscaling enabled)."
  type        = number
  default     = 20
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t3.micro"
}

# ---------------------------------------------------------------------------
# ChromaDB host (dedicated EC2 + EBS) EBS --> Elastic Block Store
# ---------------------------------------------------------------------------

variable "chroma_instance_type" {
  description = "EC2 instance type for the ChromaDB host."
  type        = string
  default     = "t3.small"
}

variable "chroma_ebs_size" {
  description = "EBS volume size (GB) for ChromaDB persistence."
  type        = number
  default     = 8
}

variable "chroma_image" {
  description = "ChromaDB container image to run on the host."
  type        = string
  default     = "chromadb/chroma:latest"
}

# ---------------------------------------------------------------------------
# Application secrets — populated into AWS Secrets Manager
# ---------------------------------------------------------------------------

variable "claude_api_key" {
  description = "Anthropic API key (Claude — all LLM calls)."
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key (embeddings only)."
  type        = string
  sensitive   = true
}

variable "alpha_vantage_api_key" {
  description = "Alpha Vantage API key (news sentiment)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "jwt_secret_key" {
  description = "Secret used to sign JWT auth tokens."
  type        = string
  sensitive   = true
}

# Optional fallback market-data providers. The DataAgent fallback chain is
# yfinance → Massive → Twelve Data → EODHD → Tiingo; yfinance needs no key.
# Leave blank to disable that source — blanks are coalesced so Secrets Manager
# still gets a valid (placeholder) value.

variable "massive_api_key" {
  description = "Massive API key (fallback market data)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "twelvedata_api_key" {
  description = "Twelve Data API key (fallback market data)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "eodhd_api_key" {
  description = "EODHD API key (fallback market data)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "tiingo_api_key" {
  description = "Tiingo API key (fallback market data)."
  type        = string
  sensitive   = true
  default     = ""
}

# ---------------------------------------------------------------------------
# ECS / ALB  (Week 7)
# ---------------------------------------------------------------------------

variable "api_image_tag" {
  description = "Image tag for the API container in ECR."
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Image tag for the frontend container in ECR."
  type        = string
  default     = "latest"
}

variable "api_cpu" {
  description = "Fargate CPU units for an API task (1024 = 1 vCPU). The in-image reranker runs on CPU."
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Fargate memory (MB) for an API task. Needs headroom for torch + the reranker model."
  type        = number
  default     = 4096
}

variable "frontend_cpu" {
  description = "Fargate CPU units for a frontend task."
  type        = number
  default     = 256
}

variable "frontend_memory" {
  description = "Fargate memory (MB) for a frontend task."
  type        = number
  default     = 512
}

variable "api_desired_count" {
  description = "Baseline number of API tasks (also the autoscaling minimum)."
  type        = number
  default     = 1
}

variable "api_max_count" {
  description = "Autoscaling maximum number of API tasks."
  type        = number
  default     = 3
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the ECS services."
  type        = number
  default     = 14
}

# ---------------------------------------------------------------------------
# CI/CD + observability  (Week 8)
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "GitHub repository as 'owner/repo' — scopes which repo's Actions workflows may assume the OIDC deploy role."
  type        = string
}

variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications. Blank disables the email subscription (alarms still publish to SNS)."
  type        = string
  default     = ""
}
