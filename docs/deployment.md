# Deployment guide — zero to cloud

Prerequisites: an AWS account, `aws` CLI + `terraform` + `docker` installed,
a free [DuckDNS](https://www.duckdns.org) subdomain, and API keys for
Gemini/Groq/LangSmith (all free tiers).

## 1. Configure

```bash
aws configure                      # IAM user with programmatic access
cp .env.example .env               # then fill in:
#   SITE_DOMAIN=<your>.duckdns.org
#   DUCKDNS_TOKEN=...              (duckdns.org, shown after login)
#   INGEST_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
#   DASH_USER / DASH_PASS_HASH     (docker run --rm caddy:2 caddy hash-password --plaintext 'pass',
#                                   escape every $ as $$ in .env)
#   GEMINI_API_KEY / GROQ_API_KEY / LANGCHAIN_API_KEY
ssh-keygen -t ed25519 -N "" -f ~/.ssh/news_ai_ed25519
```

## 2. Build the Lambda package

```bash
./scripts/build_lambda.sh          # arm64 zip via docker → dist/lambda.zip
```

## 3. Provision

```bash
cd infra/terraform && terraform init
TF_VAR_ingest_api_key=$(grep '^INGEST_API_KEY=' ../../.env | cut -d= -f2) \
TF_VAR_news_feeds=$(grep '^NEWS_FEEDS=' ../../.env | cut -d= -f2) \
terraform apply \
  -var "ssh_cidr=$(curl -s https://checkip.amazonaws.com)/32" \
  -var "ingest_url=https://<your>.duckdns.org/produce"
```

Creates: t4g.small EC2 (docker + swap + repo via user_data), Elastic IP, security
group (22 from your IP, 80/443 public), S3 backup bucket + instance role,
Lambda (python3.12 arm64), EventBridge `rate(5 minutes)`, CloudWatch logs.

## 4. Deploy the app

```bash
./scripts/deploy_ec2.sh
```

Points DuckDNS at the EIP, syncs `.env` over SSH (secrets never enter git or
Terraform state), pulls main, and starts the compose stack with the `edge`
profile (Caddy fetches its Let's Encrypt certificate automatically).

Within ~5 minutes the first EventBridge tick flows articles end to end:
`https://<your>.duckdns.org` → dashboard (basic auth).

## Operations

| Task | Command |
|---|---|
| Redeploy after code change | `git push && ./scripts/deploy_ec2.sh` |
| Update Lambda | `./scripts/build_lambda.sh` then `terraform apply` (same vars) |
| Your home IP changed (SSH blocked) | re-run `terraform apply` with the new `ssh_cidr` |
| Logs | `ssh … 'cd news-ai-platform && docker compose logs -f scheduler'`; Lambda: `aws logs tail /aws/lambda/news-ai-ingest` |
| Backups | nightly cron → S3 (14-day lifecycle); restore = copy the file back |
| Tear down | `terraform destroy` (same vars) — leaves nothing billable |
