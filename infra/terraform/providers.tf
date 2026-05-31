provider "aws" {
  region = var.aws_region

  # Every resource created by this stack is tagged uniformly — makes cost
  # allocation and "what is this?" cleanup trivial.
  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
