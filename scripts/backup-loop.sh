#!/bin/bash
# Background loop that backs up vault changes every 5 minutes

VAULT_DIR="/vault"
PERSONAL_DIRS="Cellar/1_Wines Cellar/1_Whiskeys"
INTERVAL=300  # 5 minutes

echo "Backup loop started (interval: ${INTERVAL}s)"

while true; do
    sleep $INTERVAL

    cd "$VAULT_DIR"

    # Check if there are any changes
    has_changes=false
    for dir in $PERSONAL_DIRS; do
        if [ -d "$dir" ]; then
            changes=$(git status --porcelain "$dir" 2>/dev/null | wc -l)
            if [ "$changes" -gt 0 ]; then
                has_changes=true
                break
            fi
        fi
    done

    if [ "$has_changes" = true ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Changes detected, backing up..."

        # Stage personal data directories
        for dir in $PERSONAL_DIRS; do
            if [ -d "$dir" ]; then
                git add --force "$dir" 2>/dev/null || true
            fi
        done

        # Commit if there are staged changes
        if ! git diff --cached --quiet; then
            TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
            git commit -m "Auto-backup bottles - $TIMESTAMP"
            git push origin tastings-backup
            echo "$(date '+%Y-%m-%d %H:%M:%S') - Backup complete"
        fi
    fi
done
