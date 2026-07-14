output "public_ip" {
  value = aws_eip.host.public_ip
}

output "instance_id" {
  value = aws_instance.host.id
}

output "backup_bucket" {
  value = aws_s3_bucket.backup.bucket
}

output "ssh" {
  value = "ssh -i ~/.ssh/news_ai_ed25519 ubuntu@${aws_eip.host.public_ip}"
}
