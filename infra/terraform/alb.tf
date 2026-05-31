# ---------------------------------------------------------------------------
# Application Load Balancer
#
# One internet-facing ALB fronts both services on a single hostname, split by
# URL path:
#   /analyze*, /report*, /ticker*, /history*, /conversations*, /auth*,
#   /health*, /docs*, /openapi.json   → API service
#   everything else                   → frontend service
#
# Because both services share one hostname, the browser loads the frontend
# and calls the API as the *same origin* — no CORS complexity, no second
# domain needed. HTTP only (portfolio-grade); see README for adding HTTPS.
# ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  tags = { Name = "${local.name_prefix}-alb" }
}

# Fargate tasks register by IP (awsvpc networking) → target_type = "ip".

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_target_group" "frontend" {
  name        = "${local.name_prefix}-frontend-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

# HTTP listener — frontend is the default; API paths are split off by a rule.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

# A listener rule allows at most 5 path-pattern values, so the 9 API prefixes
# are split across two rules — both forward to the same API target group.
resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/analyze*", "/report*", "/ticker*",
        "/history*", "/conversations*",
      ]
    }
  }
}

resource "aws_lb_listener_rule" "api_extra" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 110

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/auth*", "/health*", "/docs*", "/openapi.json"]
    }
  }
}
