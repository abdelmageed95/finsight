# ---------------------------------------------------------------------------
# GitHub Actions OIDC — lets the CI/CD deploy workflow obtain short-lived AWS
# credentials by federating with GitHub's OIDC provider. No long-lived access
# keys are stored in the repository.
#
# After `apply`, copy the `github_actions_role_arn` output into the GitHub repo
# as an Actions *variable* named AWS_DEPLOY_ROLE_ARN (Settings → Secrets and
# variables → Actions → Variables).
# ---------------------------------------------------------------------------

# The OIDC identity provider for GitHub Actions — one per AWS account.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub's CA thumbprint. AWS verifies the TLS chain itself now, but the
  # argument is still required by the API.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# Trust policy — only workflows from the configured repository, presenting an
# `sts.amazonaws.com` audience, may assume the deploy role.
data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Pin to the main branch — the deploy workflow only runs on push to main.
    # The `:*` wildcard would let any branch, tag, or workflow_dispatch from a
    # feature branch assume the production deploy role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${local.name_prefix}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# Permissions the deploy workflow needs: push images to ECR, run the migration
# task, roll the ECS services, and look up infra values (ALB DNS, subnets, SG).
data "aws_iam_policy_document" "github_deploy" {
  # --- ECR: authenticate, then push images ---------------------------------
  statement {
    sid       = "ECRAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "ECRPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
    resources = [
      aws_ecr_repository.api.arn,
      aws_ecr_repository.frontend.arn,
    ]
  }

  # --- ECS: run the migration task, roll the services ----------------------
  statement {
    sid = "ECSDeploy"
    actions = [
      "ecs:RunTask",
      "ecs:UpdateService",
      "ecs:DescribeServices",
      "ecs:DescribeTasks",
      "ecs:ListTasks",
      "ecs:DescribeTaskDefinition",
    ]
    resources = ["*"]
  }

  # RunTask launches a task that uses the ECS roles, so the workflow must be
  # allowed to pass them — scoped to exactly those two roles.
  statement {
    sid     = "PassECSRoles"
    actions = ["iam:PassRole"]
    resources = [
      aws_iam_role.ecs_task_execution.arn,
      aws_iam_role.ecs_task.arn,
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  # --- Read-only lookups the workflow uses to resolve infra values ---------
  statement {
    sid = "DescribeInfra"
    actions = [
      "ec2:DescribeSubnets",
      "ec2:DescribeSecurityGroups",
      "elasticloadbalancing:DescribeLoadBalancers",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${local.name_prefix}-github-deploy"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
