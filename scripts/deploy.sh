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
echo "Deployed at $(date)"
