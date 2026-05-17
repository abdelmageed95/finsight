#!/bin/bash
# EC2 user-data bootstrap for FinSight API.
#
# Runs on first boot of an Amazon Linux 2023 instance. Installs Docker,
# pulls the API image from ECR, and launches the container wired to the
# managed RDS / ElastiCache / (self-hosted) Chroma endpoints.
#
# Expected to be rendered by Terraform with these shell vars substituted:
#   AWS_REGION, ECR_REPO, IMAGE_TAG, DATABASE_URL, REDIS_URL,
#   CHROMA_HOST, CHROMA_PORT, JWT_SECRET_KEY, OPENAI_API_KEY_SECRET_ARN

set -euxo pipefail

# ---------------------------------------------------------------------------
# 1. System packages + Docker
# ---------------------------------------------------------------------------
dnf update -y
dnf install -y docker awscli jq
systemctl enable --now docker
usermod -aG docker ec2-user

# ---------------------------------------------------------------------------
# 2. Pull secrets from AWS Secrets Manager
# ---------------------------------------------------------------------------
OPENAI_API_KEY=$(aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${OPENAI_API_KEY_SECRET_ARN}" \
    --query SecretString --output text)

# ---------------------------------------------------------------------------
# 3. Authenticate Docker to ECR and pull the image
# ---------------------------------------------------------------------------
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_REPO%/*}"

docker pull "${ECR_REPO}:${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# 4. Run the container
# ---------------------------------------------------------------------------
docker rm -f finsight-api 2>/dev/null || true

docker run -d \
    --name finsight-api \
    --restart unless-stopped \
    -p 8000:8000 \
    -e DATABASE_URL="${DATABASE_URL}" \
    -e REDIS_URL="${REDIS_URL}" \
    -e CHROMA_HOST="${CHROMA_HOST}" \
    -e CHROMA_PORT="${CHROMA_PORT}" \
    -e JWT_SECRET_KEY="${JWT_SECRET_KEY}" \
    -e OPENAI_API_KEY="$OPENAI_API_KEY" \
    --log-driver=awslogs \
    --log-opt awslogs-region="${AWS_REGION}" \
    --log-opt awslogs-group=/finsight/api \
    --log-opt awslogs-create-group=true \
    "${ECR_REPO}:${IMAGE_TAG}" \
    sh -c "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 8000"
