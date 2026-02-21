#!/bin/bash
# Background loop that backs up vault changes every 5 minutes

VAULT_DIR="/vault"
PERSONAL_DIRS="Cellar/1_Wines Cellar/1_Whiskeys"
INTERVAL=300  # 5 minutes

echo "Backup loop started (interval: ${INTERVAL}s)"

while true; do
    sleep $INTERVAL

    cd "$VAULT_DIR"

    # Stage personal data directories (--force overrides .gitignore)
    for dir in $PERSONAL_DIRS; do
        if [ -d "$dir" ]; then
            git add --force "$dir" 2>/dev/null || true
        fi
    done

    # Commit and push if anything was staged
    if ! git diff --cached --quiet; then
        echo "$(date +'%Y-%m-%d %H:%M:%S') - Changes detected, backing up..."
        TIMESTAMP=$(date +"%Y-%m-%d %H:%M")
        git commit -m "Auto-backup bottles - $TIMESTAMP"
        git push origin tastings-backup
        echo "$(date +'%Y-%m-%d %H:%M:%S') - Backup complete"
    fi
done
