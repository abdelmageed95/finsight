locals {
  # Every resource name is prefixed with this — e.g. "finsight-prod-vpc".
  name_prefix = "${var.project}-${var.environment}"
}

# Use the first two AZs in the region for the two-subnet-tier layout.
data "aws_availability_zones" "available" {
  state = "available"
}
