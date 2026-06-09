#!/bin/bash
# Trigger the email digest by calling the backend on localhost.
# Called by cron twice daily (7am and 5pm UTC).
# Reads CRON_SECRET directly from the application .env file — the secret
# is never transmitted over the network or stored in environment variables
# accessible to other processes.
#
# Installation: sudo cp infra/cron/digest-trigger.sh /usr/local/bin/digest-trigger.sh
#               sudo chmod 750 /usr/local/bin/digest-trigger.sh
#               sudo chown root:appuser /usr/local/bin/digest-trigger.sh

set -euo pipefail

ENV_FILE="/home/appuser/email-summary-bot/.env"
BACKEND_URL="http://127.0.0.1:8000"
LOG_TAG="email-summary-bot-cron"

if [[ ! -f "$ENV_FILE" ]]; then
    logger -t "$LOG_TAG" "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

# Extract CRON_SECRET from .env without sourcing the entire file.
# Strips surrounding quotes if present.
CRON_SECRET=$(grep -E '^CRON_SECRET=' "$ENV_FILE" | cut -d= -f2- | sed "s/^['\"]//;s/['\"]$//")

if [[ -z "$CRON_SECRET" ]]; then
    logger -t "$LOG_TAG" "ERROR: CRON_SECRET not set in $ENV_FILE"
    exit 1
fi

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BACKEND_URL/digest/run" \
    -H "X-Cron-Secret: $CRON_SECRET" \
    --max-time 15)

if [[ "$HTTP_STATUS" == "202" ]]; then
    logger -t "$LOG_TAG" "Digest triggered (HTTP 202)"
else
    logger -t "$LOG_TAG" "ERROR: Unexpected HTTP $HTTP_STATUS from $BACKEND_URL/digest/run"
    exit 1
fi
