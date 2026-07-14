variable "region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t4g.small" # ARM, 2 GB — fits the full stack; ~$12/mo from credits
}

variable "ssh_cidr" {
  type        = string
  description = "CIDR allowed to SSH (your ip/32); pass at apply time"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/news_ai_ed25519.pub"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/Zia-ullah-code/news-ai-platform.git"
}
