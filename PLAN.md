# email-summary-bot — Implementation Plan

## Guiding Principles

- **Build the core loop first.** The digest pipeline is the whole product.
  Get emails → summarize → send working end-to-end before any UI polish.
- **Test each phase before moving on.** Each phase ends with explicit verification steps.
- **Prefer simplicity.** If a library adds complexity without clear benefit, skip it.
- **Use `.env` for everything secret.** Never hardcode tokens or keys.
- **Develop locally, deploy to Lightsail.** Local dev mirrors production closely —
  same Python version, same SQLite, same env vars.
- **Design for extensibility from day one.** The source/destination provider pattern
  must be in place before any concrete implementations, so adding Gmail or Teams
  later never requires refactoring.

---

## Phase 0 — Project Setup & Repo Structure (Day 1)

### Goals
Initialize the repo, directory structure, provider abstractions, and local dev environment.
The provider interfaces get defined here — before any concrete implementation —
so the pattern is locked in from the start.

### Steps

1. **Create repo structure:**
```
email-summary-bot/
  backend/
    main.py
    routers/
      auth.py             # /auth/{source}/url + callback (generic)
      digest.py           # /digest/preview + /digest/run
      destinations.py     # /destinations/{type}/connect + disconnect
      users.py            # /users/me/settings CRUD
    services/
      sources/
        base.py           # EmailSource ABC + EmailMessage dataclass
        outlook.py        # MS Graph implementation (Phase 2)
      destinations/
        base.py           # DigestDestination ABC
        telegram.py       # Telegram implementation (Phase 4)
      summarizer.py       # Claude API + prompt assembly (Phase 3)
      token_store.py      # AES-256 encrypt/decrypt helpers
      registry.py         # SOURCE_PROVIDERS + DESTINATION_PROVIDERS dicts
    models.py             # Pydantic request/response schemas
    db.py                 # SQLite connection + all query functions
    schema.sql            # DB schema — run once on deploy
    requirements.txt
    .env.example
  frontend/               # Next.js app (Phase 6)
  scripts/
    test_fetch.py         # Manual email fetch test
    test_summarize.py     # Manual summarization test
    backup-db.sh          # S3 backup script
    deploy.sh             # Pull + restart on Lightsail
  infra/
    nginx.conf            # nginx reverse proxy config
    email-summary-bot.service  # systemd unit file
  .github/
    workflows/
      digest.yml          # Cron trigger
  ARCHITECTURE.md
  PLAN.md
  CLAUDE.md
  .gitignore
  README.md
```

2. **Define provider abstractions** (`services/sources/base.py`, `services/destinations/base.py`).
   These are ABCs only — no implementations yet. See ARCHITECTURE.md for the full interface.

3. **Create provider registry** (`services/registry.py`) with empty dicts.
   Implementations are registered here as they are built.

4. **Initialize backend:**
```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn httpx python-dotenv cryptography aiosqlite pydantic
pip freeze > requirements.txt
```

5. **Initialize frontend:**
```bash
cd frontend
npx create-next-app@latest . --typescript --tailwind --app
npm install next-auth axios
```

6. **Create local SQLite DB:**
```bash
sqlite3 ./backend/dev.sqlite < backend/schema.sql
sqlite3 ./backend/dev.sqlite ".tables"   # confirm all 5 tables exist
```

7. **Set `DB_PATH=./dev.sqlite`** in local `.env`. All other vars can be blank for now.

8. **Create `.gitignore`:**
```
.env
*.env.local
venv/
__pycache__/
.next/
node_modules/
*.sqlite
*.db
```

### ✅ Verification
- `uvicorn main:app --reload` starts without errors
- `GET http://localhost:8000/health` returns `{"status": "ok"}`
- `sqlite3 dev.sqlite ".tables"` shows: `users source_tokens destination_config digest_settings digest_runs`
- Next.js dev server starts: `npm run dev`
- `from services.sources.base import EmailSource` imports without error
- `from services.destinations.base import DigestDestination` imports without error

---

## Phase 1 — Infra: Lightsail Server Setup (Days 2–3)

### Goals
Configure the Lightsail instance as a production-ready host before any application
code is deployed. Getting infra right early means deployment is never a blocker.

### Steps

1. **Create deploy user:**
```bash
ssh admin@your-lightsail-ip
sudo adduser appuser
sudo usermod -aG sudo appuser
# Copy your SSH public key to /home/appuser/.ssh/authorized_keys
```

2. **Install system dependencies:**
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
  nginx certbot python3-certbot-nginx sqlite3 git
```

3. **Point a domain at Lightsail:**
   - DNS A record: `api.yourdomain.com → <lightsail-ip>`
   - Wait for propagation before running Certbot

4. **Configure nginx:**
```bash
sudo cp infra/nginx.conf /etc/nginx/sites-available/email-summary-bot
sudo ln -s /etc/nginx/sites-available/email-summary-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

5. **Obtain TLS certificate:**
```bash
sudo certbot --nginx -d api.yourdomain.com
sudo systemctl status certbot.timer   # confirm auto-renewal is active
```

6. **Create app directory and DB location:**
```bash
sudo mkdir -p /var/lib/email-summary-bot
sudo chown appuser:appuser /var/lib/email-summary-bot
```

7. **Clone repo and install backend:**
```bash
cd /home/appuser
git clone https://github.com/YOUR_USERNAME/email-summary-bot.git
cd email-summary-bot/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

8. **Create `.env` on server** (copy `.env.example`, fill in all values):
```bash
cp .env.example .env
nano .env
# Set DB_PATH=/var/lib/email-summary-bot/db.sqlite
# Generate keys: openssl rand -hex 32  (TOKEN_ENCRYPTION_KEY)
#                openssl rand -hex 24  (CRON_SECRET)
```

9. **Initialize production DB:**
```bash
sqlite3 /var/lib/email-summary-bot/db.sqlite < backend/schema.sql
chmod 600 /var/lib/email-summary-bot/db.sqlite
```

10. **Install and start systemd service:**
```bash
sudo cp infra/email-summary-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable email-summary-bot
sudo systemctl start email-summary-bot
```

11. **Configure Lightsail firewall** (in Lightsail console → Networking):
    - Allow TCP 80 (nginx redirects to 443)
    - Allow TCP 443
    - Restrict SSH (22) to your IP if possible

12. **Set up S3 backup:**
```bash
# Confirm awscli is configured
aws s3 ls

# Create bucket if needed
aws s3 mb s3://your-backup-bucket

# Install backup script
sudo cp scripts/backup-db.sh /usr/local/bin/backup-db.sh
sudo chmod +x /usr/local/bin/backup-db.sh

# Schedule daily at 3am UTC
echo "0 3 * * * appuser /usr/local/bin/backup-db.sh" | sudo tee /etc/cron.d/db-backup
```

Set an S3 lifecycle rule (AWS console → S3 → your bucket → Management → Lifecycle)
to delete backups older than 30 days.

13. **Create `scripts/deploy.sh`** for future deploys:
```bash
#!/bin/bash
set -e
cd /home/appuser/email-summary-bot
git pull origin main
cd backend
source venv/bin/activate
pip install -r requirements.txt -q
sudo systemctl restart email-summary-bot
echo "Deployed at $(date)"
```

### ✅ Verification
- `curl https://api.yourdomain.com/health` returns `{"status": "ok"}` over HTTPS
- `sudo systemctl status email-summary-bot` shows `active (running)`
- Browser shows valid TLS certificate (no warning) at `https://api.yourdomain.com`
- Port 80 redirects to 443
- `sudo certbot renew --dry-run` succeeds
- Manual backup: `sudo -u appuser /usr/local/bin/backup-db.sh`
  → file appears in S3 bucket
- `journalctl -u email-summary-bot -f` shows uvicorn startup logs

---

## Phase 2 — Email Fetch: Outlook Source (Days 4–6)

### Goals
Implement the Outlook source provider. This is the first concrete implementation
of the `EmailSource` interface.

### Steps

1. **Register an Azure app:**
   - portal.azure.com → App registrations → New registration
   - Add redirect URIs:
     - `http://localhost:8000/auth/outlook/callback` (local)
     - `https://api.yourdomain.com/auth/outlook/callback` (production)
   - Permissions: `Mail.Read`, `offline_access` (delegated)
   - Copy Client ID and Client Secret to `.env` (local and server)

2. **Implement `services/sources/outlook.py`** — `OutlookSource(EmailSource)`:
   - `get_auth_url(user_id)` — builds Microsoft OAuth consent URL
   - `handle_callback(user_id, code)` — exchanges code, encrypts tokens, stores in `source_tokens`
   - `fetch_emails(user_id, since)` — calls MS Graph, maps response to `EmailMessage` list
   - `revoke(user_id)` — deletes row from `source_tokens`
   - Auto-refresh: before each fetch, check `expires_at` and refresh if needed

3. **Register in `services/registry.py`:**
```python
from services.sources.outlook import OutlookSource
SOURCE_PROVIDERS = {"outlook": OutlookSource()}
```

4. **Implement generic auth router** `routers/auth.py`:
   - `GET /auth/{source}/url` — looks up provider in registry, returns auth URL
   - `POST /auth/{source}/callback` — looks up provider, calls `handle_callback`

5. **Test script** `scripts/test_fetch.py`:
```python
# Complete OAuth flow in browser, then:
emails = await SOURCE_PROVIDERS["outlook"].fetch_emails("test-user-id", since=yesterday)
print(f"Fetched {len(emails)} emails")
for e in emails[:3]:
    print(e)
```

### ✅ Verification
- OAuth flow completes in browser (test locally first, then against production URL)
- Tokens stored encrypted in `source_tokens` table —
  `sqlite3 dev.sqlite "SELECT provider, provider_email FROM source_tokens"`
- `test_fetch.py` returns real `EmailMessage` objects from your inbox
- Token refresh works: set `expires_at` to a past value in DB, re-run fetch,
  confirm it auto-refreshes and updates the DB
- `revoke()` removes the row — confirmed with sqlite3

---

## Phase 3 — Summarization (Days 7–9)

### Goals
Build the summarization service using the Claude API.
This is the most important phase — spend time getting prompt quality right.
The summarizer is source-agnostic: it receives `list[EmailMessage]` regardless of origin.

### Steps

1. **Get Anthropic API key** from console.anthropic.com. Add to `.env`.

2. **Implement `services/summarizer.py`**:
   - `build_prompt(user_email, digest_prefs, emails: list[EmailMessage])` — prompt assembly
   - `summarize(user_id, emails)` — calls Claude API, parses and validates JSON response
   - On `JSONDecodeError`: retry once, then raise a clean error
   - Log `input_tokens`, `output_tokens` on every call

3. **Implement `POST /digest/preview`** in `routers/digest.py`:
```
Request body:
  user_id: str
  source: str = "outlook"          # which source provider to fetch from
  since_hours: int = 24            # lookback window
  digest_prefs_override: str | None  # if set, use instead of DB prefs

Steps:
  1. Fetch emails via SOURCE_PROVIDERS[source].fetch_emails(...)
  2. Summarize with Claude (use override prefs if provided)
  3. Return structured JSON + token_usage metadata
```

4. **Test script** `scripts/test_summarize.py`:
```python
result = await summarize_for_user("test-user-id", source="outlook")
import json; print(json.dumps(result, indent=2))
```

5. **Iterate on prompt quality:**
   - Urgency classification feels right
   - Todos are real action items (not noise)
   - FYI correctly captures newsletters / low-signal emails
   - Thread replies (same `conversation_id`) grouped, not listed separately

### ✅ Verification
- `POST /digest/preview` returns valid JSON with all four sections
  (`urgent`, `action_required`, `fyi`, `todos`)
- Run against 20+ real emails and manually verify quality
- Malformed model output (simulate by monkey-patching the response)
  is handled gracefully — returns error JSON, does not crash
- Token usage logged — cost per digest confirmed under $0.01
- `digest_prefs_override` in the request body changes the output meaningfully
- Passing a different `source` value falls through to registry lookup correctly
  (returns 404 if unregistered)

---

## Phase 4 — Telegram Destination (Days 10–11)

### Goals
Implement the Telegram destination provider — the first concrete `DigestDestination`.

### Steps

1. **Create Telegram bot:**
   - Message `@BotFather` → `/newbot`
   - Copy bot token to `.env`

2. **Register webhook** (Telegram pushes events to your server):
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://api.yourdomain.com/destinations/telegram/webhook"
```

3. **Implement `services/destinations/telegram.py`** — `TelegramDestination(DigestDestination)`:
   - `connect(user_id, config)` — encrypt and store `chat_id` in `destination_config`
   - `send_digest(user_id, digest)` — format digest JSON to Markdown, send via Bot API,
     split at 4096 chars into numbered messages
   - `disconnect(user_id)` — delete row from `destination_config`
   - `format_digest_markdown(digest)` — pure formatting function (no I/O, easy to test)

4. **Register in `services/registry.py`:**
```python
from services.destinations.telegram import TelegramDestination
DESTINATION_PROVIDERS = {"telegram": TelegramDestination()}
```

5. **Implement `POST /destinations/telegram/webhook`** in `routers/destinations.py`:
   - `/start` → call `connect()`, store `chat_id`, send welcome message
   - `/digest` → fetch + summarize + send for the requesting user
   - `/pause` / `/resume` → toggle `enabled` in `digest_settings`
   - `/status` → reply with last run time and email count

6. **Connect delivery to preview:**
   - Add `destination: str | None` param to `POST /digest/preview`
   - If set, call `DESTINATION_PROVIDERS[destination].send_digest(...)` after summarizing

7. **End-to-end test:**
```bash
curl -X POST http://localhost:8000/digest/preview \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "source": "outlook", "destination": "telegram"}'
```

### ✅ Verification
- `/start` to the bot stores `chat_id` in `destination_config` (verify with sqlite3)
- Digest arrives in Telegram with correct formatting — urgent first, todos at bottom
- Empty digest (no new emails) sends a friendly message, not an error or silence
- Digest with 50+ emails splits into numbered Telegram messages without truncation
- `/pause`, `/resume`, `/status` all respond correctly
- Passing an unregistered `destination` value returns a clean 404

---

## Phase 5 — Scheduled Digest (Days 12–13)

### Goals
Wire up the cron-triggered full pipeline. Every user's configured sources
and destinations run automatically on schedule.

### Steps

1. **Implement `POST /digest/run`** in `routers/digest.py`:
   - Validate `X-Cron-Secret` header — return 403 immediately if wrong
   - Query all users with `enabled=1` and schedule matching current UTC slot
   - For each user:
     - For each connected source in `source_tokens`: fetch emails since `last_run_at`
     - Merge and deduplicate emails across sources (by `id`)
     - Summarize merged list
     - For each connected destination in `destination_config`: send digest
     - Update `last_run_at` in `digest_settings`
     - Log to `digest_runs` (one row per source/destination pair)
   - Each user's failure is isolated — a Graph API error for user A must not
     prevent user B from getting their digest

2. **GitHub Actions workflow** `.github/workflows/digest.yml`:
```yaml
on:
  schedule:
    - cron: '0 7 * * *'    # 7am UTC morning
    - cron: '0 17 * * *'   # 5pm UTC evening
  workflow_dispatch:         # Manual trigger from Actions UI

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger digest run
        run: |
          curl -X POST ${{ secrets.BACKEND_URL }}/digest/run \
            -H "X-Cron-Secret: ${{ secrets.CRON_SECRET }}" \
            --fail --max-time 30
```

3. **Add secrets to GitHub repo** (Settings → Secrets → Actions):
   - `BACKEND_URL=https://api.yourdomain.com`
   - `CRON_SECRET=<same as in server .env>`

### ✅ Verification
- `POST /digest/run` with correct secret triggers digest — message arrives on Telegram
- Wrong/missing secret returns 403 immediately
- Manual trigger via GitHub Actions UI (workflow_dispatch) works end-to-end
- Scheduled runs fire at correct UTC times (check Actions tab after 24h)
- `digest_runs` records each run: status, email count, tokens used
- A user with `enabled=0` is skipped entirely
- A user with no new emails since `last_run_at` gets no Telegram message
- Simulate one user's source failing (revoke their token) — other users unaffected

---

## Phase 6 — Frontend: Onboarding & Settings (Days 14–18)

### Goals
Build the web UI so users can self-onboard and manage their settings
without touching code or the database.

### Steps

1. **NextAuth.js setup** — email magic link (Resend free tier):
   - Session stored as JWT, passed as `Authorization: Bearer` to backend
   - Backend validates JWT on all `/users/me/*` routes

2. **Onboarding wizard** `/onboard` — 3 steps:
   - Step 1: "Connect your email" — shows available sources from `SOURCE_PROVIDERS` keys;
     clicking "Connect Outlook" redirects to `/auth/outlook/url`
   - Step 2: "Connect your destination" — shows available destinations from
     `DESTINATION_PROVIDERS` keys; clicking "Connect Telegram" shows bot instructions
     and polls for `chat_id` confirmation
   - Step 3: "Customize your digest" — textarea for `digest_prefs`, schedule picker

   The UI reads available providers dynamically via `GET /providers` so adding
   a new source or destination in the backend automatically surfaces it in the UI.

3. **Settings page** `/settings`:
   - Manage connected sources (add / disconnect)
   - Manage connected destinations (add / disconnect)
   - Edit digest prefs
   - Change schedule / pause / resume

4. **Backend endpoints:**
   - `GET /providers` — return lists of registered source and destination provider keys
   - `GET /users/me/settings`
   - `PUT /users/me/settings`
   - `DELETE /users/me/sources/{provider}` — calls `revoke()`, removes row
   - `DELETE /users/me/destinations/{provider}` — calls `disconnect()`, removes row

5. **Deploy frontend to Vercel:**
```bash
cd frontend && npx vercel
# Set NEXT_PUBLIC_API_URL and NEXTAUTH_* in Vercel dashboard
```

### ✅ Verification
- New user completes full onboarding without any technical knowledge
- Settings changes persist — confirmed by reading back from DB
- A second independent user can onboard — both receive separate, correct digests
- Disconnecting Outlook calls `revoke()` and removes tokens from `source_tokens`
- Disconnecting Telegram removes `destination_config` row — no further delivery
- `GET /providers` returns correct lists (add a stub provider to registry,
  confirm it appears without frontend changes)

---

## Phase 7 — Frontend: Preview & Prompt Tuning (Days 19–21)

### Goals
Let users run the digest on demand in the browser, see the result,
edit the prompt, and re-run. This is the core UX for tuning digest quality.

### Steps

1. **Preview page** `/preview`:
   - Source picker (from `GET /providers`) — which inbox to fetch from
   - Time range toggle: Last 24h / 48h / 7 days
   - "Run digest now" button → `POST /digest/preview`
   - Loading spinner with estimated time (5–15s)
   - Render structured digest as cards:
     - Collapsible sections: Urgent / Action Required / FYI / Todos
     - Each email: subject, sender, one-line summary, suggested action
   - Token usage + estimated cost shown below result

2. **Prompt editor panel:**
   - Textarea pre-filled with current `digest_prefs`
   - "Re-run with this prompt" — passes `digest_prefs_override` to preview endpoint
   - "Save as default" — `PUT /users/me/settings`

3. **"Send to Telegram" button** (or whichever destinations the user has connected).

### ✅ Verification
- Preview renders within 15 seconds for a 20–30 email inbox
- Editing the prompt and re-running produces a meaningfully different result
- "Save as default" reflected in next scheduled digest (check `digest_settings` in DB)
- Token count and cost shown match Anthropic console usage
- Page is usable on mobile (Tailwind responsive layout)
- Source picker correctly shows only providers the user has connected

---

## Phase 8 — Hardening & Polish (Days 22–26)

### Goals
Make the system reliable enough to run unattended for weeks.

### Steps

1. **Error resilience:**
   - Source token refresh fails → send message to all user's destinations:
     "Your Outlook connection expired — reconnect at [link]"
   - Claude API fails → retry once with 2s backoff; log and skip user on second failure
   - Destination send fails → log error, mark `digest_runs` row as `error`;
     do not retry (avoid duplicate messages)
   - Failures are always per-user and never cascade

2. **Safety caps:**
   - Max 100 emails per digest per source (fetch top 100 by recency, note truncation in digest)
   - Max 300 chars of `bodyPreview` per email sent to LLM
   - Telegram: split messages at 4096 chars, label as "Part 1/2" etc.

3. **Observability:**
   - `GET /admin/stats` (protected by cron secret) — runs per user, avg token cost, error rate
   - All application logs to stdout → visible via `journalctl -u email-summary-bot`

4. **Auto-renewal verification:**
```bash
sudo certbot renew --dry-run
```

5. **README.md** — complete setup guide covering: Azure app registration,
   Lightsail configuration, Vercel deploy, all env vars, and first user onboarding.
   Target: a new developer can set up the full stack in under 30 minutes.

### ✅ Verification
- Simulate source failure: revoke a token and trigger a run →
  user receives reconnect message on Telegram; other users unaffected
- Simulate Claude timeout: set 1s timeout temporarily →
  error logged, run continues for next user
- 50-email digest splits correctly across multiple Telegram messages
- `GET /admin/stats` returns accurate run counts and error rates
- `sudo certbot renew --dry-run` succeeds
- Developer following README alone sets up full stack in < 30 minutes

---

## Summary Timeline

| Phase | Focus | Duration |
|---|---|---|
| 0 | Project setup, provider abstractions | Day 1 |
| 1 | Lightsail infra: nginx, TLS, systemd, S3 backup | Days 2–3 |
| 2 | Outlook source provider | Days 4–6 |
| 3 | Summarization + prompt tuning | Days 7–9 |
| 4 | Telegram destination provider + bot commands | Days 10–11 |
| 5 | Scheduled digest (cron) | Days 12–13 |
| 6 | Frontend: onboarding + settings | Days 14–18 |
| 7 | Frontend: preview + prompt tuning | Days 19–21 |
| 8 | Hardening + polish | Days 22–26 |

**Total: ~4 weeks** for a production-ready v1.

---

## Adding Sources & Destinations Later

The provider pattern makes this straightforward — no refactoring needed.

**To add Gmail (example):**
1. Create `services/sources/gmail.py` implementing `EmailSource`
2. Add `"gmail": GmailSource()` to `SOURCE_PROVIDERS` in `registry.py`
3. Add Google OAuth credentials to `.env`
4. `GET /providers` automatically surfaces it in the frontend

**To add Microsoft Teams (example):**
1. Create `services/destinations/teams.py` implementing `DigestDestination`
2. Add `"teams": TeamsDestination()` to `DESTINATION_PROVIDERS` in `registry.py`
3. Add Teams webhook config to `.env`
4. `GET /providers` automatically surfaces it in the frontend

No changes to the scheduler, summarizer, database schema, or frontend logic.

---

## Open Questions to Revisit Later

- **Thread collapsing:** Group reply chains by `conversation_id` — v2 feature.
- **Attachments:** Flag emails with attachments in the digest — easy to add to `EmailMessage`.
- **Multiple accounts per source:** e.g. two Outlook accounts. Schema supports it
  (no unique constraint on `user_id` alone), but UI and fetch logic need updating.
- **Read-only filter:** Option to digest only unread emails — add as a setting in Phase 6.
- **Digest history:** Store and browse past digests in the UI — v2 feature.
- **Litestream:** Continuous WAL replication to S3 — worth it if digest history is stored.
