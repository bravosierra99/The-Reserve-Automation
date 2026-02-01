#!/bin/bash
set -e

echo "=== Reserve Automation Container Startup ==="

# Git configuration for commits
git config --global user.email "reserve-automation@docker.smith"
git config --global user.name "Reserve Automation"
git config --global --add safe.directory /vault

# Pull latest vault data
echo "[1/3] Pulling latest vault (tastings-backup branch)..."
cd /vault
git fetch origin
git reset --hard origin/tastings-backup
echo "Vault updated: $(git log -1 --format='%h %s')"

# Start backup cron job in background
echo "[2/3] Starting backup scheduler (every 5 minutes)..."
/app/scripts/backup-loop.sh &

# Start the application
echo "[3/3] Starting Reserve Automation..."
exec uv run uvicorn reserve_automation.web.app:app --host 0.0.0.0 --port 8000
