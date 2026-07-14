data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "ubuntu_arm64" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

resource "aws_key_pair" "deploy" {
  key_name   = "news-ai-deploy"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "host" {
  name        = "news-ai-host"
  description = "SSH from operator; HTTP/HTTPS to Caddy only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "ssh (operator only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  ingress {
    description = "acme http challenge"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "https (caddy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- Nightly DuckDB backup target ---

resource "aws_s3_bucket" "backup" {
  bucket_prefix = "news-ai-backup-"
  force_destroy = true # demo project: terraform destroy must be clean
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {}

    expiration {
      days = 14
    }
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "news-ai-host"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "backup_rw" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.backup.arn, "${aws_s3_bucket.backup.arn}/*"]
  }
}

resource "aws_iam_role_policy" "backup" {
  name   = "backup-rw"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.backup_rw.json
}

resource "aws_iam_instance_profile" "host" {
  name = "news-ai-host"
  role = aws_iam_role.host.name
}

# --- The host ---

resource "aws_instance" "host" {
  ami                    = data.aws_ami.ubuntu_arm64.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deploy.key_name
  vpc_security_group_ids = [aws_security_group.host.id]
  iam_instance_profile   = aws_iam_instance_profile.host.name

  credit_specification {
    cpu_credits = "standard" # burstable throttles instead of billing extra
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url      = var.repo_url
    backup_bucket = aws_s3_bucket.backup.bucket
  })

  tags = {
    Name = "news-ai-host"
  }
}

resource "aws_eip" "host" {
  domain = "vpc"
}

resource "aws_eip_association" "host" {
  instance_id   = aws_instance.host.id
  allocation_id = aws_eip.host.id
}
