#!/usr/bin/env bash
# ===========================================================================
# deploy.sh — first-deploy / redeploy helper for the FinSight AWS stack.
#
# Run this AFTER `terraform apply` has created the infrastructure. `apply`
# builds the plumbing (ECR registries, ECS services, RDS, ...) but cannot put
# *images* on the registries or *tables* in the database — that is this
# script's job. It performs, in order:
#
#   1. read connection details from `terraform output`
#   2. log Docker in to ECR
#   3. build + push the API image
#   4. build + push the frontend image (ALB URL baked in at build time)
#   5. run the DB migration task once  (alembic upgrade head)
#   6. force a fresh deployment of both ECS services
#   7. wait for the services to stabilise
#
# Safe to re-run: this is exactly the sequence for every redeploy. Week 8
# reimplements it in GitHub Actions so a plain `git push` does the same thing.
#
# Usage:    infra/scripts/deploy.sh
# Requires: aws CLI (configured), docker (running), jq, terraform.
# Env override (optional):
#   IMAGE_TAG   image tag to build/push (default: latest — must match the
#               api_image_tag / frontend_image_tag Terraform variables).
# ===========================================================================
set -euo pipefail

# --- Resolve paths so the script works from any directory ------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$REPO_ROOT/infra/terraform"
IMAGE_TAG="${IMAGE_TAG:-latest}"

cd "$TF_DIR"

# --- Sanity checks ---------------------------------------------------------
for cmd in aws docker jq terraform; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: required command '$cmd' is not in PATH." >&2
    exit 1
  }
done

if ! terraform output -raw ecr_api_repository_url >/dev/null 2>&1; then
  echo "ERROR: no Terraform outputs found in $TF_DIR." >&2
  echo "       Run 'terraform apply' before running this script." >&2
  exit 1
fi

# --- Step 1: read everything Terraform knows -------------------------------
echo "==> [1/7] Reading Terraform outputs"
AWS_REGION="$(terraform output -raw aws_region)"
API_REPO="$(terraform output -raw ecr_api_repository_url)"
FRONTEND_REPO="$(terraform output -raw ecr_frontend_repository_url)"
ALB_URL="$(terraform output -raw application_url)"
CLUSTER="$(terraform output -raw ecs_cluster_name)"
API_SVC="$(terraform output -raw ecs_api_service_name)"
FRONTEND_SVC="$(terraform output -raw ecs_frontend_service_name)"
MIGRATE_FAMILY="$(terraform output -raw migration_task_family)"
API_SG="$(terraform output -raw ecs_api_security_group_id)"
SUBNETS="$(terraform output -json private_subnet_ids | jq -r 'join(",")')"
REGISTRY="${API_REPO%/*}"   # strip the repo name → bare ECR host

echo "    region:     $AWS_REGION"
echo "    image tag:  $IMAGE_TAG"
echo "    ALB URL:    $ALB_URL"

# --- Step 2: authenticate Docker to ECR ------------------------------------
echo "==> [2/7] Logging Docker in to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

# --- Step 3: build + push the API image ------------------------------------
# --platform linux/amd64: Fargate tasks run X86_64; building on an ARM host
# without this produces an image that will not start in AWS.
echo "==> [3/7] Building + pushing the API image (slow — installs torch)"
docker build --platform linux/amd64 -t "$API_REPO:$IMAGE_TAG" "$REPO_ROOT"
docker push "$API_REPO:$IMAGE_TAG"

# --- Step 4: build + push the frontend image -------------------------------
# Next.js inlines NEXT_PUBLIC_* at *build* time, so the ALB URL must be passed
# now — it cannot be changed by an env var at runtime.
echo "==> [4/7] Building + pushing the frontend image"
docker build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_API_URL="$ALB_URL" \
  -t "$FRONTEND_REPO:$IMAGE_TAG" "$REPO_ROOT/frontend"
docker push "$FRONTEND_REPO:$IMAGE_TAG"

# --- Step 5: run the DB migration once -------------------------------------
echo "==> [5/7] Running the DB migration task (alembic upgrade head)"
TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$MIGRATE_FAMILY" \
  --launch-type FARGATE \
  --network-configuration \
    "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$API_SG],assignPublicIp=DISABLED}" \
  --region "$AWS_REGION" \
  --query 'tasks[0].taskArn' --output text)"

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" = "None" ]; then
  echo "ERROR: migration task failed to launch." >&2
  exit 1
fi
echo "    task: $TASK_ARN"
echo "    waiting for migration to finish..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$AWS_REGION"

EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --region "$AWS_REGION" --query 'tasks[0].containers[0].exitCode' --output text)"
if [ "$EXIT_CODE" != "0" ]; then
  echo "ERROR: migration exited with code '$EXIT_CODE'." >&2
  echo "       Check CloudWatch log group /ecs/<name-prefix>/api, stream 'migrate'." >&2
  exit 1
fi
echo "    migration succeeded"

# --- Step 6: roll both services onto the freshly-pushed images -------------
# The tag stays the same ($IMAGE_TAG), so ECS only notices the new image when
# told to redeploy. This same command is how every future redeploy works.
echo "==> [6/7] Forcing a new deployment of both services"
aws ecs update-service --cluster "$CLUSTER" --service "$API_SVC" \
  --force-new-deployment --region "$AWS_REGION" >/dev/null
aws ecs update-service --cluster "$CLUSTER" --service "$FRONTEND_SVC" \
  --force-new-deployment --region "$AWS_REGION" >/dev/null

# --- Step 7: wait for healthy ----------------------------------------------
echo "==> [7/7] Waiting for services to stabilise (several minutes)"
aws ecs wait services-stable --cluster "$CLUSTER" \
  --services "$API_SVC" "$FRONTEND_SVC" --region "$AWS_REGION"

echo
echo "Deployment complete. Open: $ALB_URL"
