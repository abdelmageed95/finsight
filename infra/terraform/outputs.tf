# Consumed by Week 7 (ECS/ALB) and by CI/CD; also handy for eyeballing the
# stack after `terraform apply`.

output "aws_region" {
  description = "Region the stack is deployed in (read by infra/scripts/deploy.sh)."
  value       = var.aws_region
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "ecr_api_repository_url" {
  description = "Push the API image here."
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_frontend_repository_url" {
  description = "Push the frontend image here."
  value       = aws_ecr_repository.frontend.repository_url
}

output "rds_endpoint" {
  description = "Postgres host:port."
  value       = aws_db_instance.main.endpoint
}

output "redis_endpoint" {
  description = "Redis primary endpoint."
  value       = "${aws_elasticache_cluster.main.cache_nodes[0].address}:6379"
}

output "chroma_private_ip" {
  description = "Private IP the API uses as CHROMA_HOST."
  value       = aws_instance.chroma.private_ip
}

output "secret_arns" {
  description = "Secrets Manager ARNs, keyed by name."
  value       = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
}

# --- Week 7: ECS / ALB ------------------------------------------------------

output "alb_dns_name" {
  description = "Public hostname of the load balancer."
  value       = aws_lb.main.dns_name
}

output "application_url" {
  description = "Open this in a browser once images are pushed and tasks are healthy."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_api_service_name" {
  value = aws_ecs_service.api.name
}

output "ecs_frontend_service_name" {
  value = aws_ecs_service.frontend.name
}

output "migration_task_family" {
  description = "Task definition family for the one-shot DB migration (run with `aws ecs run-task`)."
  value       = aws_ecs_task_definition.migrate.family
}

output "ecs_api_security_group_id" {
  description = "Security group for API/migration tasks — needed in the `run-task` network config."
  value       = aws_security_group.ecs_api.id
}

# --- Week 8: CI/CD + observability -----------------------------------------

output "github_actions_role_arn" {
  description = "Copy this into the GitHub repo as the Actions variable AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.github_actions.arn
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard for the stack."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards/dashboard/${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "sns_alerts_topic_arn" {
  description = "SNS topic every CloudWatch alarm publishes to."
  value       = aws_sns_topic.alerts.arn
}
