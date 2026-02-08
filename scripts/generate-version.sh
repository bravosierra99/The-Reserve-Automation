#!/bin/bash
# Generate version.json file with git information for Docker builds
# This captures build-time git state since .git directory isn't copied to container

set -e

VERSION_FILE="src/reserve_automation/version.json"

echo "Generating version.json..."

# Check if we're in a git repository
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "WARNING: Not in a git repository, creating minimal version.json"
    cat > "$VERSION_FILE" << EOF
{
  "version": "dev",
  "commit": "unknown",
  "commit_short": "unknown",
  "branch": "unknown",
  "clean": null,
  "commit_message": "Built outside git repository",
  "commit_date": null,
  "build_date": "$(date -Iseconds)"
}
EOF
    exit 0
fi

# Get git information
COMMIT=$(git rev-parse HEAD)
COMMIT_SHORT=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
COMMIT_MESSAGE=$(git log -1 --pretty=%B | head -n1)
COMMIT_DATE=$(git log -1 --format=%ai)

# Get version from git tags (e.g., v1.2.3)
# Uses latest tag, or "dev" if no tags exist
VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "dev")
# If tag has 'v' prefix, remove it (v1.2.3 -> 1.2.3)
VERSION=${VERSION#v}

# Check if working directory is clean
if [ -z "$(git status --porcelain)" ]; then
    CLEAN="true"
else
    CLEAN="false"
fi

# Generate JSON file
cat > "$VERSION_FILE" << EOF
{
  "version": "$VERSION",
  "commit": "$COMMIT",
  "commit_short": "$COMMIT_SHORT",
  "branch": "$BRANCH",
  "clean": $CLEAN,
  "commit_message": $(echo "$COMMIT_MESSAGE" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read().strip()))'),
  "commit_date": "$COMMIT_DATE",
  "build_date": "$(date -Iseconds)"
}
EOF

echo "✓ Generated $VERSION_FILE"
echo "  Version: $VERSION"
echo "  Commit: $COMMIT_SHORT ($BRANCH)"
echo "  Clean: $CLEAN"
echo "  Date: $COMMIT_DATE"
