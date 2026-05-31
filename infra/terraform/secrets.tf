# ---------------------------------------------------------------------------
# AWS Secrets Manager — sensitive runtime config. The ECS task definitions
# (Week 7) inject these into the API container via `secrets:` valueFrom, so
# no key is ever baked into an image or committed.
#
# recovery_window_in_days = 0 → a `terraform destroy` frees the names
# immediately, so the stack can be torn down and recreated cleanly.
# ---------------------------------------------------------------------------

locals {
  secrets = {
    claude-api-key = var.claude_api_key
    openai-api-key = var.openai_api_key
    # Secrets Manager rejects an empty value; coalesce so a blank
    # (news-disabled) key still produces a valid secret.
    alpha-vantage-api-key = coalesce(var.alpha_vantage_api_key, "unset")
    jwt-secret-key        = var.jwt_secret_key
    # Optional fallback market-data providers — blank → placeholder.
    massive-api-key    = coalesce(var.massive_api_key, "unset")
    twelvedata-api-key = coalesce(var.twelvedata_api_key, "unset")
    eodhd-api-key      = coalesce(var.eodhd_api_key, "unset")
    tiingo-api-key     = coalesce(var.tiingo_api_key, "unset")
    # Full async DSN — embeds the RDS endpoint + credentials.
    database-url = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.main.address}:5432/${var.db_name}"
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = local.secrets
  name                    = "${local.name_prefix}/${each.key}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each      = local.secrets
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = each.value
}
