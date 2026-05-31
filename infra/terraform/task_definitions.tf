# ---------------------------------------------------------------------------
# ECS task definitions — the blueprints for each container.
#
#   api      — the FastAPI + LangGraph service (long-running)
#   frontend — the Next.js server (long-running)
#   migrate  — a one-shot `alembic upgrade head`, run once per deploy
#
# Non-secret config goes in `environment`; anything sensitive comes from
# Secrets Manager via `secrets` (the ECS agent resolves the ARN at launch —
# the value never appears in the task definition or image).
# ---------------------------------------------------------------------------

locals {
  # Secrets the API task pulls from Secrets Manager.
  api_secrets = [
    { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.app["database-url"].arn },
    { name = "CLAUDE_API_KEY", valueFrom = aws_secretsmanager_secret.app["claude-api-key"].arn },
    { name = "OPENAI_API_KEY", valueFrom = aws_secretsmanager_secret.app["openai-api-key"].arn },
    { name = "ALPHA_VANTAGE_API_KEY", valueFrom = aws_secretsmanager_secret.app["alpha-vantage-api-key"].arn },
    { name = "JWT_SECRET_KEY", valueFrom = aws_secretsmanager_secret.app["jwt-secret-key"].arn },
    { name = "MASSIVE_API_KEY", valueFrom = aws_secretsmanager_secret.app["massive-api-key"].arn },
    { name = "TWELVEDATA_API_KEY", valueFrom = aws_secretsmanager_secret.app["twelvedata-api-key"].arn },
    { name = "EODHD_API_KEY", valueFrom = aws_secretsmanager_secret.app["eodhd-api-key"].arn },
    { name = "TIINGO_API_KEY", valueFrom = aws_secretsmanager_secret.app["tiingo-api-key"].arn },
  ]
}

# --- API --------------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [
      { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/0" },
      { name = "CHROMA_HOST", value = aws_instance.chroma.private_ip },
      { name = "CHROMA_PORT", value = "8000" },
      { name = "CORS_ORIGINS", value = "http://${aws_lb.main.dns_name}" },
      # The in-app APScheduler is disabled: with N autoscaled tasks each would
      # fire the same refresh. Scheduled ingestion belongs on EventBridge.
      { name = "SCHEDULER_ENABLED", value = "false" },
    ]

    secrets = local.api_secrets

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

# --- Frontend ---------------------------------------------------------------
# NEXT_PUBLIC_API_URL is *not* set here — Next.js inlines NEXT_PUBLIC_* vars at
# build time, so CI bakes it into the image (see Week 8).

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "frontend"
    image     = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"
    essential = true

    portMappings = [{ containerPort = 3000, protocol = "tcp" }]

    environment = [
      { name = "NODE_ENV", value = "production" },
      { name = "PORT", value = "3000" },
      { name = "HOSTNAME", value = "0.0.0.0" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "frontend"
      }
    }
  }])
}

# --- Migration (one-shot) ---------------------------------------------------
# Same image as the API, but overrides the command to run Alembic. Launched
# with `aws ecs run-task` once per deploy (by CI in Week 8) — never as a
# service. This keeps schema migrations off the critical path of N autoscaled
# API tasks racing the same `alembic upgrade head`.

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "migrate"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true
    command   = ["alembic", "upgrade", "head"]

    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.app["database-url"].arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])
}
