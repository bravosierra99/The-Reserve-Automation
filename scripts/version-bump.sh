#!/bin/bash
# Unified version bump script
# Updates both pyproject.toml AND git tag to keep versions in sync
#
# Usage:
#   ./scripts/version-bump.sh patch              # 0.3.8 -> 0.3.9
#   ./scripts/version-bump.sh minor              # 0.3.8 -> 0.4.0
#   ./scripts/version-bump.sh major              # 0.3.8 -> 1.0.0
#   ./scripts/version-bump.sh 1.2.3              # Set explicit version
#   ./scripts/version-bump.sh --dry-run patch    # Preview changes

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Parse arguments
DRY_RUN=false
BUMP_TYPE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run|-n)
            DRY_RUN=true
            shift
            ;;
        --yes|-y)
            YES=true
            shift
            ;;
        *)
            BUMP_TYPE="$1"
            shift
            ;;
    esac
done

if [ -z "$BUMP_TYPE" ]; then
    echo -e "${RED}Error: Must specify bump type or version${NC}"
    echo "Usage: $0 [--dry-run] <patch|minor|major|X.Y.Z>"
    exit 1
fi

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep "^version = " pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo -e "${BLUE}Current version: ${CURRENT_VERSION}${NC}"

# Calculate new version
if [[ "$BUMP_TYPE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # Explicit version provided
    NEW_VERSION="$BUMP_TYPE"
else
    # Parse semantic version
    IFS='.' read -r -a VERSION_PARTS <<< "$CURRENT_VERSION"
    MAJOR="${VERSION_PARTS[0]}"
    MINOR="${VERSION_PARTS[1]}"
    PATCH="${VERSION_PARTS[2]}"

    case "$BUMP_TYPE" in
        major)
            MAJOR=$((MAJOR + 1))
            MINOR=0
            PATCH=0
            ;;
        minor)
            MINOR=$((MINOR + 1))
            PATCH=0
            ;;
        patch)
            PATCH=$((PATCH + 1))
            ;;
        *)
            echo -e "${RED}Error: Invalid bump type '$BUMP_TYPE'${NC}"
            echo "Must be: patch, minor, major, or X.Y.Z"
            exit 1
            ;;
    esac

    NEW_VERSION="$MAJOR.$MINOR.$PATCH"
fi

echo -e "${GREEN}New version: ${NEW_VERSION}${NC}"

# Check if tag already exists
if git rev-parse "v$NEW_VERSION" >/dev/null 2>&1; then
    echo -e "${RED}Error: Tag v$NEW_VERSION already exists${NC}"
    exit 1
fi

if [ "$DRY_RUN" = true ]; then
    echo -e "\n${YELLOW}DRY RUN - Would perform these actions:${NC}"
    echo "  1. Update pyproject.toml: version = \"$NEW_VERSION\""
    echo "  2. Commit: \"Bump version to $NEW_VERSION\""
    echo "  3. Create tag: v$NEW_VERSION"
    echo "  4. Push commits and tags to origin"
    exit 0
fi

# Confirm with user (skip if --yes)
echo -e "\n${YELLOW}This will:${NC}"
echo "  1. Update pyproject.toml to version $NEW_VERSION"
echo "  2. Commit the change"
echo "  3. Create git tag v$NEW_VERSION"
echo "  4. Push to origin (commits + tags)"
echo ""
if [[ "${YES}" != "true" ]]; then
    read -p "Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Aborted${NC}"
        exit 0
    fi
fi

# Update pyproject.toml
echo -e "\n${BLUE}Updating pyproject.toml...${NC}"
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml

# Verify the change
NEW_VERSION_CHECK=$(grep "^version = " pyproject.toml | sed 's/version = "\(.*\)"/\1/')
if [ "$NEW_VERSION_CHECK" != "$NEW_VERSION" ]; then
    echo -e "${RED}Error: Failed to update pyproject.toml${NC}"
    git checkout pyproject.toml  # Revert
    exit 1
fi
echo -e "${GREEN}✓ Updated pyproject.toml${NC}"

# Commit the version bump
echo -e "\n${BLUE}Committing version bump...${NC}"
git add pyproject.toml
git commit -m "Bump version to $NEW_VERSION"
echo -e "${GREEN}✓ Committed${NC}"

# Create git tag
echo -e "\n${BLUE}Creating git tag v$NEW_VERSION...${NC}"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
echo -e "${GREEN}✓ Tagged v$NEW_VERSION${NC}"

# Push everything
echo -e "\n${BLUE}Pushing to origin...${NC}"
git push origin main
git push origin --tags
echo -e "${GREEN}✓ Pushed to origin${NC}"

echo -e "\n${GREEN}=== Version bumped successfully ===${NC}"
echo -e "  Old version: ${CURRENT_VERSION}"
echo -e "  New version: ${NEW_VERSION}"
echo -e "  Git tag: v${NEW_VERSION}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. On deployment servers: git pull && git fetch --tags"
echo "  2. Rebuild Docker: ./scripts/generate-version.sh && docker compose build"
echo ""
