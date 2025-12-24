#!/bin/bash
# Dual-branch Git Backup Script
#
# Generic script for repositories using a dual-branch strategy:
# - One branch for framework/public files
# - One branch for personal/private data
#
# Originally created for The Reserve vault

set -e  # Exit on error

# ============================================================================
# CONFIGURATION - Customize these for your repository
# ============================================================================

# Determine working directory (use current directory or follow symlink)
if [ -L "$0" ]; then
    # If script is a symlink, use the directory where the symlink is located
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
else
    # Otherwise use current working directory
    SCRIPT_DIR="$(pwd)"
fi

# Change to the repository directory
cd "$SCRIPT_DIR"

# Branch names
FRAMEWORK_BRANCH="main"          # Branch for framework/public files
PERSONAL_BRANCH="tastings-backup" # Branch for personal/private data

# Directories containing personal data (space-separated)
# These will be backed up to the personal branch
PERSONAL_DIRS="Cellar/1_Wines/ Cellar/1_Whiskeys/"

# Repository name for display messages
REPO_NAME="The Reserve"

# ============================================================================
# SCRIPT BEGINS - No need to edit below this line
# ============================================================================

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== $REPO_NAME Backup ===${NC}\n"

# Check if we're in a git repo
if [ ! -d .git ]; then
    echo -e "${RED}Error: Not a git repository${NC}"
    exit 1
fi

# Parse arguments
DRY_RUN=false
if [ "$2" == "--dry-run" ] || [ "$2" == "-n" ]; then
    DRY_RUN=true
    echo -e "${YELLOW}DRY RUN MODE - No changes will be committed${NC}\n"
fi

# Function to backup personal data on personal branch
backup_personal() {
    local dry_run=$1

    echo -e "${YELLOW}Backing up personal data...${NC}"

    # Ensure we're on personal branch
    current_branch=$(git branch --show-current)
    if [ "$current_branch" != "$PERSONAL_BRANCH" ]; then
        echo -e "${BLUE}Switching to $PERSONAL_BRANCH branch${NC}"
        if [ "$dry_run" = false ]; then
            git checkout "$PERSONAL_BRANCH"
        fi
    fi

    # Merge framework into personal to get framework updates
    if [ "$dry_run" = false ]; then
        echo -e "${BLUE}Syncing framework changes from $FRAMEWORK_BRANCH...${NC}"
        # Only merge if there are differences
        if ! git diff --quiet "$PERSONAL_BRANCH...$FRAMEWORK_BRANCH"; then
            git merge "$FRAMEWORK_BRANCH" --no-edit -m "Sync framework updates from $FRAMEWORK_BRANCH"
            echo -e "${GREEN}✓ Merged $FRAMEWORK_BRANCH into $PERSONAL_BRANCH${NC}"
        else
            echo -e "${GREEN}Already up to date with $FRAMEWORK_BRANCH${NC}"
        fi
    fi

    # Show what would be added
    echo -e "\n${BLUE}Files to stage:${NC}"
    for dir in $PERSONAL_DIRS; do
        echo "  - $dir"
    done

    if [ "$dry_run" = false ]; then
        # Stage ONLY personal data files
        for dir in $PERSONAL_DIRS; do
            git add "$dir" 2>/dev/null || true
        done
    fi

    # Check if there are changes
    if [ "$dry_run" = false ]; then
        if git diff --cached --quiet; then
            echo -e "\n${GREEN}No changes to personal data${NC}"
            return
        fi

        # Show what's being committed
        echo -e "\n${BLUE}Changes to commit:${NC}"
        git diff --cached --stat

        # Commit with timestamp
        TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
        git commit -m "Backup personal data - $TIMESTAMP"
        echo -e "\n${GREEN}✓ Committed personal data changes${NC}"

        # Push to remote
        echo -e "\n${YELLOW}Pushing to remote...${NC}"
        git push origin "$PERSONAL_BRANCH"
        echo -e "${GREEN}✓ Pushed to origin/$PERSONAL_BRANCH${NC}"
    else
        # Dry run: show what would be committed
        echo -e "\n${BLUE}Would commit these changes:${NC}"
        for dir in $PERSONAL_DIRS; do
            git diff --stat "$dir" 2>/dev/null
        done
        [ -z "$(git diff --stat $PERSONAL_DIRS 2>/dev/null)" ] && echo "  (no changes)"
    fi
}

# Function to backup framework on framework branch
backup_framework() {
    local dry_run=$1

    echo -e "\n${YELLOW}Backing up framework files...${NC}"

    # Ensure we're on framework branch
    current_branch=$(git branch --show-current)
    if [ "$current_branch" != "$FRAMEWORK_BRANCH" ]; then
        echo -e "${BLUE}Switching to $FRAMEWORK_BRANCH branch${NC}"
        if [ "$dry_run" = false ]; then
            git checkout "$FRAMEWORK_BRANCH"
        fi
    fi

    # Show what would be added (everything except personal data)
    echo -e "\n${BLUE}Files to stage (excluding personal data):${NC}"
    echo "  - All files except:"
    for dir in $PERSONAL_DIRS; do
        echo "    • $dir"
    done

    if [ "$dry_run" = false ]; then
        # Stage ALL changes first
        git add -A

        # Then unstage personal data
        for dir in $PERSONAL_DIRS; do
            git reset "$dir" 2>/dev/null || true
        done
    fi

    # Check if there are changes
    if [ "$dry_run" = false ]; then
        if git diff --cached --quiet; then
            echo -e "\n${GREEN}No changes to framework${NC}"
            return
        fi

        # Show what's being committed
        echo -e "\n${BLUE}Changes to commit:${NC}"
        git diff --cached --stat

        # Commit with timestamp
        TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
        git commit -m "Update framework - $TIMESTAMP"
        echo -e "\n${GREEN}✓ Committed framework changes${NC}"

        # Push to remote
        echo -e "\n${YELLOW}Pushing to remote...${NC}"
        git push origin "$FRAMEWORK_BRANCH"
        echo -e "${GREEN}✓ Pushed to origin/$FRAMEWORK_BRANCH${NC}"
    else
        # Dry run: show what would be committed
        # Temporarily stage to show diff, then unstage
        git add -A 2>/dev/null || true
        for dir in $PERSONAL_DIRS; do
            git reset "$dir" 2>/dev/null || true
        done

        echo -e "\n${BLUE}Would commit these changes:${NC}"
        git diff --cached --stat 2>/dev/null || echo "  (no changes)"

        # Unstage everything
        git reset 2>/dev/null || true
    fi
}

# Function to show status
show_status() {
    echo -e "${BLUE}=== Current Status ===${NC}\n"

    # Show current branch
    CURRENT_BRANCH=$(git branch --show-current)
    echo -e "Current branch: ${GREEN}$CURRENT_BRANCH${NC}\n"

    # Show uncommitted changes by category
    echo -e "${BLUE}Uncommitted changes:${NC}\n"

    # Check personal data
    local has_personal_changes=false
    for dir in $PERSONAL_DIRS; do
        if ! git diff --quiet "$dir" 2>/dev/null; then
            has_personal_changes=true
            break
        fi
    done

    if [ "$has_personal_changes" = true ]; then
        echo -e "${YELLOW}Personal Data (goes to $PERSONAL_BRANCH):${NC}"
        for dir in $PERSONAL_DIRS; do
            git status --short "$dir" 2>/dev/null
        done | head -10
        echo ""
    fi

    # Check framework
    git add -A 2>/dev/null || true
    for dir in $PERSONAL_DIRS; do
        git reset "$dir" 2>/dev/null || true
    done

    if ! git diff --cached --quiet 2>/dev/null; then
        echo -e "${YELLOW}Framework (goes to $FRAMEWORK_BRANCH):${NC}"
        git diff --cached --stat 2>/dev/null | head -10
        echo ""
    fi

    # Reset staging
    git reset 2>/dev/null || true

    if git diff --quiet && git diff --cached --quiet; then
        echo -e "${GREEN}No uncommitted changes${NC}"
    fi
}

# Main logic
case "${1:-both}" in
    personal|bottles)
        backup_personal $DRY_RUN
        ;;
    framework)
        backup_framework $DRY_RUN
        ;;
    both)
        backup_personal $DRY_RUN
        backup_framework $DRY_RUN
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {personal|framework|both|status} [--dry-run|-n]"
        echo ""
        echo "Commands:"
        echo "  personal   - Backup personal data to $PERSONAL_BRANCH branch (alias: bottles)"
        echo "  framework  - Backup framework files to $FRAMEWORK_BRANCH branch"
        echo "  both       - Backup both (default)"
        echo "  status     - Show current git status by category"
        echo ""
        echo "Options:"
        echo "  --dry-run, -n  - Show what would be done without making changes"
        echo ""
        echo "Examples:"
        echo "  $0 personal --dry-run"
        echo "  $0 both"
        echo "  $0 status"
        exit 1
        ;;
esac

# Always switch back to personal branch when done (unless we're just showing status)
if [ "$DRY_RUN" = false ] && [ "${1:-both}" != "status" ]; then
    CURRENT_BRANCH=$(git branch --show-current)
    if [ "$CURRENT_BRANCH" != "$PERSONAL_BRANCH" ]; then
        echo -e "\n${BLUE}Switching back to $PERSONAL_BRANCH branch...${NC}"
        git checkout "$PERSONAL_BRANCH"
    fi
    echo -e "\n${GREEN}=== Backup Complete ===${NC}"
fi
