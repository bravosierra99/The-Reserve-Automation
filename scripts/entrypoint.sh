#!/bin/bash
set -e

echo "=== Reserve Automation Container Startup ==="

mkdir -p /app/data/media

echo "Starting Reserve Automation v1.0.0..."
exec uv run uvicorn reserve_automation.web.app:app --host 0.0.0.0 --port 8000
