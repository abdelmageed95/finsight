# ---------------------------------------------------------------------------
# IAM roles
#   ecs_task_execution — used by the ECS agent: pull from ECR, write logs,
#                        read the app secrets. (Used to *launch* a task.)
#   ecs_task           — assumed by the running container itself.
#   chroma_ec2         — instance profile for the ChromaDB host (SSM access).
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- ECS task execution role ------------------------------------------------

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${local.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Lets the ECS agent resolve the `secrets:` block of the task definition.
data "aws_iam_policy_document" "ecs_read_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for s in aws_secretsmanager_secret.app : s.arn]
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name   = "${local.name_prefix}-ecs-read-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_read_secrets.json
}

# --- ECS task role (the running container) ----------------------------------
# The app reaches Anthropic/OpenAI/SEC over HTTPS with keys from env, and its
# datastores over the network — it makes no AWS API calls, so this role holds
# no policies. It exists so execution vs runtime permissions stay separated.

resource "aws_iam_role" "ecs_task" {
  name               = "${local.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# --- ChromaDB EC2 instance profile ------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "chroma_ec2" {
  name               = "${local.name_prefix}-chroma-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# SSM Session Manager — admin access without opening an SSH port.
resource "aws_iam_role_policy_attachment" "chroma_ssm" {
  role       = aws_iam_role.chroma_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Lets the host ship Docker/system logs to CloudWatch.
resource "aws_iam_role_policy_attachment" "chroma_cw" {
  role       = aws_iam_role.chroma_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "chroma_ec2" {
  name = "${local.name_prefix}-chroma-ec2"
  role = aws_iam_role.chroma_ec2.name
}
