# email-summary-bot

A multi-user email digest service. Fetches emails from Outlook (Microsoft Graph),
summarizes them with Claude (Anthropic AI), and delivers structured digests via Telegram.

**Stack:** Python/FastAPI · Next.js · SQLite · Claude Haiku · MS Graph API · Telegram Bot API  
**Cost:** ~$5/month (AWS Lightsail + Anthropic API)

---

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design.
See [PLAN.md](./PLAN.md) for the phased build history.

---

## Local Development Setup

This guide gets you running the full stack locally in under 30 minutes.

### Prerequisites

- Python 3.11+
- Node.js 18+
- An Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- A Microsoft Azure app registration (for Outlook OAuth)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

---

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/email-summary-bot.git
cd email-summary-bot
```

---

### 2. Backend setup

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env` from the example:

```bash
cp .env.example .env
```

Edit `.env` and fill in these values for local development:

```bash
DB_PATH=./dev.sqlite
TOKEN_ENCRYPTION_KEY=<run: python3 -c "import secrets; print(secrets.token_hex(32))">
CRON_SECRET=<run: python3 -c "import secrets; print(secrets.token_hex(24))">
ADMIN_SECRET=<run: python3 -c "import secrets; print(secrets.token_hex(24))">
NEXTAUTH_SECRET=<any random string, must match frontend>
ANTHROPIC_API_KEY=sk-ant-...

# Microsoft (Outlook)
MS_CLIENT_ID=<from Azure portal>
MS_CLIENT_SECRET=<from Azure portal>
MS_REDIRECT_URI=http://localhost:8000/auth/outlook/callback

# Telegram
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_WEBHOOK_SECRET=<run: python3 -c "import secrets; print(secrets.token_hex(24))">

FRONTEND_URL=http://localhost:3000
```

Initialize the local SQLite database:

```bash
sqlite3 dev.sqlite < schema.sql
sqlite3 dev.sqlite ".tables"   # should show all 6 tables
```

Start the backend:

```bash
uvicorn main:app --reload
# http://localhost:8000/health → {"status": "ok"}
```

---

### 3. Frontend setup

```bash
cd ../frontend
npm install
```

Create `.env.local`:

```bash
cp .env.example .env.local
```

Edit `.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXTAUTH_SECRET=<same value as backend NEXTAUTH_SECRET>
NEXTAUTH_URL=http://localhost:3000

# For magic-link email (Resend)
RESEND_API_KEY=re_...
EMAIL_FROM=noreply@yourdomain.com
```

Start the frontend:

```bash
npm run dev
# http://localhost:3000
```

---

### 4. Azure App Registration (Outlook OAuth)

1. Go to [portal.azure.com](https://portal.azure.com) → **App registrations** → **New registration**
2. Name: `email-summary-bot-dev`
3. Redirect URI (Web): `http://localhost:8000/auth/outlook/callback`
4. Under **API permissions** → Add: `Mail.Read`, `offline_access` (delegated)
5. Under **Certificates & secrets** → New client secret → copy value
6. Copy **Application (client) ID** and the secret to your backend `.env`

---

### 5. Telegram Bot Setup

```bash
# Message @BotFather on Telegram:
/newbot
# Follow prompts, copy the token to TELEGRAM_BOT_TOKEN in .env

# For local development, use ngrok to expose your backend:
ngrok http 8000

# Register the webhook (replace with your ngrok URL):
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://YOUR_NGROK.ngrok.io/destinations/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

---

### 6. Run the tests

```bash
cd backend
source venv/bin/activate
python -m unittest discover -s tests -v
# All 249 tests should pass in under 15 seconds
```

```bash
cd frontend
npm test   # TypeScript type check
```

---

### 7. First user onboarding (local)

1. Open `http://localhost:3000` and sign in with your email
2. Go through the `/onboard` wizard:
   - Connect Outlook → authorize the Azure app
   - Connect Telegram → send `/start <code>` to your bot
   - Set digest preferences
3. Go to `/preview` → run a digest on demand to verify the pipeline
4. Check `/admin/stats` (with `X-Admin-Secret` header) to see run history

---

## Production Deployment

### AWS Lightsail

1. Provision the smallest Lightsail Linux instance (~$3.50–5/mo)
2. Follow steps 1–12 in [PLAN.md Phase 1](./PLAN.md)
3. Copy `infra/nginx.conf` and `infra/email-summary-bot.service` to the server
4. Set all env vars in `/home/appuser/email-summary-bot/.env`
5. Initialize the production DB: `sqlite3 /var/lib/email-summary-bot/db.sqlite < schema.sql`
6. Start the service: `sudo systemctl enable --now email-summary-bot`
7. Run `scripts/deploy.sh` for all future deploys (also installs/updates the cron job)

### Vercel (frontend)

```bash
cd frontend
npx vercel
# Set NEXT_PUBLIC_API_URL, NEXTAUTH_SECRET, NEXTAUTH_URL, RESEND_API_KEY in Vercel dashboard
```

### Cron scheduler (one-time setup on Lightsail)

The digest schedule runs via system cron on the same machine as the backend. No external
dependencies or GitHub secrets are required. The cron script reads `CRON_SECRET` directly
from the application `.env` file and calls uvicorn on `127.0.0.1:8000` — the call never
leaves the machine.

```bash
# Install the trigger script (requires sudo; run once on first deploy)
sudo cp infra/cron/digest-trigger.sh /usr/local/bin/digest-trigger.sh
sudo chmod 750 /usr/local/bin/digest-trigger.sh
sudo chown root:appuser /usr/local/bin/digest-trigger.sh

# Install the cron schedule (7am and 5pm UTC)
sudo cp infra/cron/email-summary-bot /etc/cron.d/email-summary-bot
sudo chmod 644 /etc/cron.d/email-summary-bot
sudo chown root:root /etc/cron.d/email-summary-bot
```

After the initial setup, `scripts/deploy.sh` keeps both files in sync automatically
on every deploy.

To verify the cron job works manually:
```bash
sudo -u appuser /usr/local/bin/digest-trigger.sh
# Digest triggered (HTTP 202)
# Or check syslog: grep email-summary-bot-cron /var/log/syslog
```

---

## Environment Variables Reference

### Backend (`backend/.env`)

| Variable | Description |
|---|---|
| `DB_PATH` | Path to SQLite file. Use `./dev.sqlite` locally, `/var/lib/email-summary-bot/db.sqlite` in prod |
| `TOKEN_ENCRYPTION_KEY` | 32-byte hex key for AES-256 token encryption (`openssl rand -hex 32`) |
| `CRON_SECRET` | Secret for `POST /digest/run` (`openssl rand -hex 24`) |
| `ADMIN_SECRET` | Secret for `GET /admin/stats` — must differ from `CRON_SECRET` |
| `NEXTAUTH_SECRET` | Shared JWT signing secret — must match the Vercel value |
| `ANTHROPIC_API_KEY` | Claude API key from console.anthropic.com |
| `FRONTEND_URL` | Frontend base URL for reconnect links (e.g. `https://your-app.vercel.app`) |
| `MS_CLIENT_ID` | Azure app client ID |
| `MS_CLIENT_SECRET` | Azure app client secret |
| `MS_REDIRECT_URI` | OAuth callback URL registered in Azure |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook validation secret (`openssl rand -hex 24`) |

### Frontend (`frontend/.env.local`)

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend API URL |
| `NEXTAUTH_SECRET` | Same value as backend |
| `NEXTAUTH_URL` | Frontend canonical URL |
| `RESEND_API_KEY` | Resend API key for magic-link email |
| `EMAIL_FROM` | From address for magic-link emails |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Liveness check |
| `GET` | `/providers` | None | List registered sources and destinations |
| `GET` | `/auth/{source}/url` | JWT | Get OAuth consent URL |
| `GET/POST` | `/auth/{source}/callback` | — | OAuth callback |
| `POST` | `/digest/preview` | JWT | On-demand digest (10/hour rate limit) |
| `POST` | `/digest/run` | Cron secret | Scheduled digest trigger (returns 202) |
| `POST` | `/destinations/telegram/link-code` | JWT | Generate Telegram link code |
| `GET` | `/destinations/telegram/status` | JWT | Check Telegram link status |
| `POST` | `/destinations/telegram/webhook` | Webhook secret | Telegram Bot webhook |
| `DELETE` | `/destinations/{type}/disconnect` | JWT | Disconnect a destination |
| `GET` | `/users/me/settings` | JWT | Get digest settings |
| `PUT` | `/users/me/settings` | JWT | Update digest settings |
| `GET` | `/users/me/sources` | JWT | List connected sources |
| `GET` | `/users/me/destinations` | JWT | List connected destinations |
| `DELETE` | `/users/me/sources/{provider}` | JWT | Disconnect a source |
| `DELETE` | `/users/me/destinations/{provider}` | JWT | Disconnect a destination |
| `GET` | `/admin/stats` | Admin secret | Digest run stats (error rate, token usage) |

---

## Security Notes

- All OAuth tokens encrypted with AES-256 (Fernet) before DB storage
- `CRON_SECRET` and `ADMIN_SECRET` are separate so they can be rotated independently
- `/digest/run` is protected by three layers: uvicorn binds to `127.0.0.1` only, nginx returns 404 for this path, and `CRON_SECRET` is validated on every request — the secret is never transmitted over the network
- The Telegram webhook validates `X-Telegram-Bot-Api-Secret-Token` on every request
- Only `bodyPreview` (≤255 chars) is sent to the LLM by default — never full email bodies
- Rate limiting on `/digest/preview`: 10 calls per user per hour
- Email cap: at most 100 emails per digest run per source (cost control)

---

## Troubleshooting

**Backend won't start:**
- Check `DB_PATH` exists and is writable
- Verify `TOKEN_ENCRYPTION_KEY` is exactly 64 hex chars (32 bytes)
- `journalctl -u email-summary-bot -f` for live logs

**Outlook OAuth fails:**
- Confirm `MS_REDIRECT_URI` in `.env` exactly matches the URI registered in Azure
- Make sure `Mail.Read` and `offline_access` delegated permissions are added

**Telegram bot not receiving messages:**
- Re-run the `setWebhook` curl command
- Confirm `TELEGRAM_WEBHOOK_SECRET` matches in both the webhook registration and `.env`
- Check ngrok is still running (for local development)

**Digests not sending:**
- Check `digest_settings.enabled = 1` and schedule matches the cron slot
- Look for errors in `digest_runs` table: `sqlite3 dev.sqlite "SELECT * FROM digest_runs WHERE status = 'error'"`
- Run `POST /admin/stats` with `X-Admin-Secret` to see aggregate error rates

**Cron job not firing:**
- Check syslog: `grep email-summary-bot-cron /var/log/syslog`
- Verify the cron file permissions: `ls -l /etc/cron.d/email-summary-bot` (must be `644`, owned by `root:root`)
- Test manually: `sudo -u appuser /usr/local/bin/digest-trigger.sh`
- Confirm `CRON_SECRET` is set in `/home/appuser/email-summary-bot/.env`
