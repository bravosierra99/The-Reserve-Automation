#!/bin/bash
# Start The Reserve web server

cd "$(dirname "$0")"

echo "Starting The Reserve web server on http://localhost:8000"
echo "Press Ctrl+C to stop"
echo ""

# Use UV's built-in .env loading
uv run --env-file .env uvicorn reserve_automation.web.app:app --host 0.0.0.0 --port 8000 --reload
