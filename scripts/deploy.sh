#!/bin/bash
set -e
cd /home/appuser/email-summary-bot
git pull origin main
cd backend
source venv/bin/activate
pip install -r requirements.txt -q
sudo systemctl restart email-summary-bot
sleep 3
systemctl is-active --quiet email-summary-bot || { echo "Service failed to start"; exit 1; }
curl -sf http://localhost:8000/health || { echo "Health check failed"; exit 1; }

# Install/update the cron trigger script and cron.d file.
sudo cp ../infra/cron/digest-trigger.sh /usr/local/bin/digest-trigger.sh
sudo chmod 750 /usr/local/bin/digest-trigger.sh
sudo chown root:appuser /usr/local/bin/digest-trigger.sh
sudo cp ../infra/cron/email-summary-bot /etc/cron.d/email-summary-bot
sudo chmod 644 /etc/cron.d/email-summary-bot
sudo chown root:root /etc/cron.d/email-summary-bot

echo "Deployed at $(date)"
