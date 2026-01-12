#!/bin/bash

# Configuration
# Default values
KEEP_DAYS=7
KEEP_COUNT=10
PROJECT_ROOT="/home/dlckdgn/personal-portfolio"
BACKUP_DIR="${PROJECT_ROOT}/backend/storage/backups"

# Allow override via arguments
if [ ! -z "$1" ]; then KEEP_DAYS=$1; fi
if [ ! -z "$2" ]; then KEEP_COUNT=$2; fi

echo "=========================================="
echo "Backup Retention Policy Execution"
echo "Target: $BACKUP_DIR"
echo "Policy: Keep $KEEP_DAYS days OR max $KEEP_COUNT files"
echo "Date: $(date)"
echo "=========================================="

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: Directory $BACKUP_DIR does not exist."
    exit 1
fi

# 1. Delete files older than $KEEP_DAYS days
echo "Step 1: Deleting backups older than $KEEP_DAYS days..."
find "$BACKUP_DIR" -type f \( -name "*.zip" -o -name "*.gz" -o -name "*.db" \) -mtime +$KEEP_DAYS -print -delete

# 2. Ensure we don't exceed $KEEP_COUNT files (safety cap)
# Get list of files sorted by modification time (oldest first)
FILES=$(ls -tr "$BACKUP_DIR"/*.zip "$BACKUP_DIR"/*.gz "$BACKUP_DIR"/*.db 2>/dev/null)
count=$(echo "$FILES" | grep -v '^$' | wc -l)

if [ "$count" -gt "$KEEP_COUNT" ]; then
    excess=$((count - KEEP_COUNT))
    echo "Step 2: Found $count files. Removing $excess oldest files to maintain limit of $KEEP_COUNT..."
    echo "$FILES" | head -n "$excess" | xargs -r rm -v
else
    echo "Step 2: Total files ($count) is within limit ($KEEP_COUNT). No additional deletion needed."
fi

echo "Done."
