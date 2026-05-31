# ---------------------------------------------------------------------------
# Security groups — least-privilege chain:
#   internet → alb → ecs(api/frontend) → rds / redis / chroma
# Each tier only accepts traffic from the tier directly in front of it.
# ---------------------------------------------------------------------------

# ALB — the only thing exposed to the internet.
resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "ALB - public HTTP/HTTPS ingress"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-alb-sg" }
}

# FastAPI Fargate tasks — only the ALB may reach port 8000.
resource "aws_security_group" "ecs_api" {
  name        = "${local.name_prefix}-ecs-api-sg"
  description = "API Fargate tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "API port from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-ecs-api-sg" }
}

# Next.js Fargate tasks — only the ALB may reach port 3000.
resource "aws_security_group" "ecs_frontend" {
  name        = "${local.name_prefix}-ecs-frontend-sg"
  description = "Frontend Fargate tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Frontend port from ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-ecs-frontend-sg" }
}

# RDS Postgres — only the API tasks may reach 5432.
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS Postgres"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from API tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-rds-sg" }
}

# ElastiCache Redis — only the API tasks may reach 6379.
resource "aws_security_group" "redis" {
  name        = "${local.name_prefix}-redis-sg"
  description = "ElastiCache Redis"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from API tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-redis-sg" }
}

# ChromaDB EC2 host — only the API tasks may reach Chroma's port 8000.
resource "aws_security_group" "chroma" {
  name        = "${local.name_prefix}-chroma-sg"
  description = "ChromaDB EC2 host"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Chroma HTTP from API tasks"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_api.id]
  }

  # Outbound only — needed to pull the Chroma image and reach SSM.
  # Admin access is via SSM Session Manager, so there is no SSH ingress.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-chroma-sg" }
}
