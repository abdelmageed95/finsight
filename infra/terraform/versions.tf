terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # State is local by default. For team use, create an S3 bucket + DynamoDB
  # lock table once, then uncomment and `terraform init -migrate-state`.
  #
  # backend "s3" {
  #   bucket         = "finsight-tfstate"
  #   key            = "prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "finsight-tflock"
  #   encrypt        = true
  # }
}
