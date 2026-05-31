# ---------------------------------------------------------------------------
# ChromaDB host — a dedicated EC2 instance running the Chroma container, with
# a separate EBS data volume so the vector store survives instance replacement.
# Lives in a private subnet: reachable only by the API tasks, never the
# internet. Admin access is via SSM Session Manager (no SSH port open).
# ---------------------------------------------------------------------------

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "chroma" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.chroma_instance_type
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.chroma.id]
  iam_instance_profile   = aws_iam_instance_profile.chroma_ec2.name

  user_data = templatefile("${path.module}/chroma_user_data.sh.tftpl", {
    chroma_image = var.chroma_image
  })

  root_block_device {
    volume_size = 10
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "${local.name_prefix}-chroma" }
}

# Persistent data volume — kept separate from the root volume so a host
# rebuild can re-attach it without losing embeddings.
resource "aws_ebs_volume" "chroma_data" {
  availability_zone = aws_instance.chroma.availability_zone
  size              = var.chroma_ebs_size
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "${local.name_prefix}-chroma-data" }
}

resource "aws_volume_attachment" "chroma_data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.chroma_data.id
  instance_id = aws_instance.chroma.id
}
