# ---------------------------------------------------------------------------
# CloudWatch observability — an SNS alert topic, metric alarms on the ALB,
# the ECS API service, and RDS, plus a single dashboard.
#
# Every alarm notifies the SNS topic. Set `alarm_email` in terraform.tfvars to
# receive emails — AWS sends a one-time confirmation link you must click.
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  # Fire the SNS topic both when an alarm trips and when it recovers.
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# --- ALB --------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name_prefix}-alb-5xx"
  alarm_description   = "ALB returned 5xx responses to clients."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_unhealthy_hosts" {
  alarm_name          = "${local.name_prefix}-api-unhealthy-hosts"
  alarm_description   = "One or more API tasks are failing ALB health checks."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

# --- ECS API service --------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "api_cpu" {
  alarm_name          = "${local.name_prefix}-api-cpu-high"
  alarm_description   = "API service CPU sustained above 85%."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }
}

resource "aws_cloudwatch_metric_alarm" "api_memory" {
  alarm_name          = "${local.name_prefix}-api-memory-high"
  alarm_description   = "API service memory sustained above 90%."
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 90
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }
}

# --- RDS --------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name_prefix}-rds-cpu-high"
  alarm_description   = "RDS CPU sustained above 85%."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${local.name_prefix}-rds-low-storage"
  alarm_description   = "RDS free storage dropped below 2 GiB."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2147483648 # 2 GiB, in bytes
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# --- Dashboard --------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name_prefix

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB — requests & 5xx"
          region = var.aws_region
          period = 300
          stat   = "Sum"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "API service — CPU / memory %"
          region = var.aws_region
          period = 300
          stat   = "Average"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", aws_ecs_service.api.name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "RDS — CPU % & free storage"
          region = var.aws_region
          period = 300
          stat   = "Average"
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.identifier],
            ["AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", aws_db_instance.main.identifier],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "ALB — target response time (p95)"
          region = var.aws_region
          period = 300
          stat   = "p95"
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix],
          ]
        }
      },
    ]
  })
}
