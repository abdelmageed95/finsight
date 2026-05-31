# ---------------------------------------------------------------------------
# ECR — Docker image registries. CI pushes here; ECS pulls from here.
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "MUTABLE"

  # force_delete lets `terraform destroy` delete the repo even with images in
  # it — otherwise teardown stalls until every image is removed by hand.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${local.name_prefix}-frontend"
  image_tag_mutability = "MUTABLE"

  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep only the last 10 images per repo — old layers are dead weight + cost.
locals {
  ecr_lifecycle_policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire all but the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = local.ecr_lifecycle_policy
}
