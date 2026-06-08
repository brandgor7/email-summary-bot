#!/bin/bash
set -e
DATE=$(date +%Y-%m-%d)
DB=/var/lib/email-summary-bot/db.sqlite
BUCKET=s3://your-backup-bucket/email-summary-bot

sqlite3 "$DB" ".backup /tmp/db-backup-$DATE.sqlite"
aws s3 cp /tmp/db-backup-$DATE.sqlite "$BUCKET/db-$DATE.sqlite"
rm /tmp/db-backup-$DATE.sqlite
echo "Backup complete: db-$DATE.sqlite"
