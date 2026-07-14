#!/usr/bin/env bash
# Deploy/update the app on the Terraform-managed EC2 host.
#   ./scripts/deploy_ec2.sh
# Reads SITE_DOMAIN + DUCKDNS_TOKEN from .env; points DNS at the EIP, syncs
# .env (secrets never live in git or terraform state), pulls latest main, and
# (re)starts the full compose stack with the edge profile.
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_KEY="${SSH_KEY:-$HOME/.ssh/news_ai_ed25519}"
SITE_DOMAIN=$(grep '^SITE_DOMAIN=' .env | cut -d= -f2)
DUCKDNS_TOKEN=$(grep '^DUCKDNS_TOKEN=' .env | cut -d= -f2)
IP=$(terraform -chdir=infra/terraform output -raw public_ip)

[ -n "$DUCKDNS_TOKEN" ] || { echo "DUCKDNS_TOKEN missing from .env"; exit 1; }

echo "==> pointing ${SITE_DOMAIN} at ${IP}"
curl -fsS "https://www.duckdns.org/update?domains=${SITE_DOMAIN%%.duckdns.org}&token=${DUCKDNS_TOKEN}&ip=${IP}" && echo

echo "==> syncing .env"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new .env "ubuntu@${IP}:news-ai-platform/.env"

echo "==> deploying"
ssh -i "$SSH_KEY" "ubuntu@${IP}" '
  set -euo pipefail
  cd news-ai-platform
  git pull --ff-only
  docker compose --profile edge up -d --build
  docker compose ps
'

echo "==> done: https://${SITE_DOMAIN}"
