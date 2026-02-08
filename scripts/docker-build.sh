#!/bin/bash
# Build Docker image with version information
# This script generates version.json before building the image

set -e

echo "==================================================================="
echo "Building Docker image with version information"
echo "==================================================================="

# Generate version.json
echo "Step 1: Generating version.json..."
./scripts/generate-version.sh

# Build Docker image
echo ""
echo "Step 2: Building Docker image..."
docker compose build "$@"

echo ""
echo "✓ Build complete!"
echo ""
echo "Version information included in image:"
cat src/reserve_automation/version.json | grep -E "(commit_short|branch|build_date)" | sed 's/^/  /'
echo ""
