# email-summary-bot — Architecture

## Overview

A multi-user email digest service that fetches emails from configurable **sources**
(currently: Microsoft Outlook), summarizes them using an LLM, and delivers structured
digests to configurable **destinations** (currently: Telegram).

The architecture is explicitly designed to support additional sources (e.g. Gmail, IMAP)
and destinations (e.g. Microsoft Teams, Slack, email) without structural changes —
only new provider implementations are needed.

---

## System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                        │
│                        Vercel — free tier                        │
│                                                                  │
│   /onboard   Connect sources + destinations, set prefs          │
│   /settings  Manage connections, digest prefs, schedule         │
│   /preview   On-demand summarize → render in-browser, tune      │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTPS (REST)
┌─────────────────────────────▼────────────────────────────────────┐
│               BACKEND (FastAPI) + DATABASE (SQLite)              │
│                    AWS Lightsail — single VPS                    │
│                                                                  │
│   FastAPI served via uvicorn, fronted by nginx (TLS)            │
│   SQLite file on local disk — no network DB required            │
│                                                                  │
│   POST /auth/{source}/callback    OAuth callback (any source)   │
│   GET  /auth/{source}/url         OAuth consent URL             │
│   POST /destinations/{type}/connect  Connect a destination      │
│   POST /digest/preview            On-demand summarize           │
│   POST /digest/run                Scheduled trigger (cron)      │
│   GET  /users/me/settings         Fetch user config             │
│   PUT  /users/me/settings         Update digest prefs           │
└──────┬───────────────────────────────────────┬───────────────────┘
       │                                       │
┌──────▼──────────────────┐      ┌─────────────▼──────────┐
│  SOURCE PROVIDERS        │      │  ANTHROPIC API         │
│  (pluggable interface)   │      │  claude-haiku-4-5      │
│                          │      │  Summarization only    │
│  ✅ MS Graph (Outlook)   │      └────────────────────────┘
│  🔲 Gmail (Google API)   │
│  🔲 IMAP (generic)       │      ┌────────────────────────┐
└──────────────────────────┘      │  DESTINATION PROVIDERS │
                                  │  (pluggable interface) │
┌─────────────────────────┐       │                        │
│  SCHEDULER              │       │  ✅ Telegram Bot API   │
│  GitHub Actions cron    │       │  🔲 MS Teams webhook   │
│  1–2x/day per user      │       │  🔲 Slack webhook      │
│  POST /digest/run       │       │  🔲 Email (SES/SMTP)   │
└─────────────────────────┘       └────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  BACKUP — AWS S3 + awscli                                        │
│  Daily cron: sqlite3 .backup → S3 bucket (30-day retention)     │
└──────────────────────────────────────────────────────────────────┘
```

Legend: ✅ Implemented in v1 — 🔲 Planned, not yet implemented

---

## Extensibility Design

### Source / Destination Provider Pattern

All email sources implement a common Python abstract interface. Adding a new source
means implementing this interface — no changes to the digest pipeline, scheduler,
or database schema.

```python
# services/sources/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

@dataclass
class EmailMessage:
    id: str
    subject: str
    sender_name: str
    sender_email: str
    body_preview: str          # First ~300 chars — what's sent to LLM by default
    received_at: datetime
    is_read: bool
    conversation_id: str | None = None
    has_attachments: bool = False

class EmailSource(ABC):
    @abstractmethod
    async def get_auth_url(self, user_id: str) -> str:
        """Return OAuth consent URL for this provider."""

    @abstractmethod
    async def handle_callback(self, user_id: str, code: str) -> None:
        """Exchange auth code for tokens and store them."""

    @abstractmethod
    async def fetch_emails(self, user_id: str, since: datetime) -> list[EmailMessage]:
        """Fetch emails since the given datetime."""

    @abstractmethod
    async def revoke(self, user_id: str) -> None:
        """Revoke access and delete stored tokens."""
```

```python
# services/destinations/base.py
from abc import ABC, abstractmethod

class DigestDestination(ABC):
    @abstractmethod
    async def connect(self, user_id: str, config: dict) -> None:
        """Store connection config (e.g. chat_id, webhook URL)."""

    @abstractmethod
    async def send_digest(self, user_id: str, digest: dict) -> None:
        """Format and deliver a digest to this destination."""

    @abstractmethod
    async def disconnect(self, user_id: str) -> None:
        """Remove stored connection config."""
```

**Provider registry** — routes requests to the right implementation:

```python
# services/registry.py
from services.sources.outlook import OutlookSource
# from services.sources.gmail import GmailSource  # future

SOURCE_PROVIDERS: dict[str, EmailSource] = {
    "outlook": OutlookSource(),
    # "gmail": GmailSource(),
}

from services.destinations.telegram import TelegramDestination
# from services.destinations.teams import TeamsDestination  # future

DESTINATION_PROVIDERS: dict[str, DigestDestination] = {
    "telegram": TelegramDestination(),
    # "teams": TeamsDestination(),
}
```

### Adding a New Source (e.g. Gmail)

1. Create `services/sources/gmail.py` implementing `EmailSource`
2. Register it in `SOURCE_PROVIDERS`
3. Add a row to `source_tokens` with `provider='gmail'`
4. Add OAuth credentials to `.env`

No other files change.

### Adding a New Destination (e.g. Microsoft Teams)

1. Create `services/destinations/teams.py` implementing `DigestDestination`
2. Register it in `DESTINATION_PROVIDERS`
3. Add a row to `destination_config` with `provider='teams'`
4. Add any credentials to `.env`

No other files change.

---

## Components

### Frontend — Next.js on Vercel

**Purpose:** User onboarding, settings management, and on-demand digest preview.

**Key pages:**

| Route | Purpose |
|---|---|
| `/` | Landing / sign-in |
| `/onboard` | Step-by-step: connect source → connect destination → set prefs |
| `/settings` | Manage connections, digest prefs, schedule |
| `/preview` | Run digest on demand, edit prompt, re-run |
| `/api/auth/[...nextauth]` | NextAuth.js session management |

The onboarding flow is source/destination agnostic — it reads available providers
from the backend and renders the appropriate connection UI for each.

**Auth:** NextAuth.js with email magic-link or GitHub OAuth for app login.
This is separate from the per-source OAuth flows (Outlook, Gmail), which are
handled backend-side.

---

### Backend — FastAPI on AWS Lightsail

**Why Lightsail over a managed platform (Fly.io, Railway, etc.):**
- Flat predictable pricing ($3.50–5/mo for the smallest instance)
- No cold starts — process stays alive, cron responses are instant
- SQLite lives on the same machine — no network latency to a remote DB
- Already set up with awscli and S3 access — no new AWS accounts or tools
- One SSH session to debug anything

**Process management:** systemd service keeps uvicorn running and restarts on crash.
**TLS:** nginx as a reverse proxy, certificate via Let's Encrypt / Certbot.

**Directory structure:**
```
backend/
  main.py
  routers/
    auth.py           # /auth/{source}/url and /auth/{source}/callback
    digest.py         # /digest/preview and /digest/run
    destinations.py   # /destinations/{type}/connect and /disconnect
    users.py          # /users/me/settings
  services/
    sources/
      base.py         # EmailSource ABC + EmailMessage dataclass
      outlook.py      # MS Graph implementation ✅
      gmail.py        # Google API implementation 🔲
    destinations/
      base.py         # DigestDestination ABC
      telegram.py     # Telegram Bot API implementation ✅
      teams.py        # MS Teams webhook implementation 🔲
      slack.py        # Slack webhook implementation 🔲
    summarizer.py     # Claude API calls + prompt assembly
    token_store.py    # AES-256 encrypt/decrypt for OAuth tokens
    registry.py       # Provider registry (source + destination maps)
  models.py           # Pydantic request/response schemas
  db.py               # SQLite connection + all query functions
  schema.sql          # DB schema — run once on first deploy
```

---

### Database — SQLite (local file on Lightsail)

**Why local SQLite over Turso or RDS:**
- Zero cost, zero network latency, zero configuration
- SQLite handles the load of 3–20 users easily
- Backup solved: daily `sqlite3 .backup` → S3 via existing awscli setup
- Simple to inspect: `sqlite3 /var/lib/email-summary-bot/db.sqlite`

**File location:** `/var/lib/email-summary-bot/db.sqlite`
Owned by the app user (`appuser`), permissions `600`. Not in the repo directory.

**Schema:**

```sql
-- App-level user identity (separate from any email provider)
CREATE TABLE users (
  id          TEXT PRIMARY KEY,      -- UUID
  email       TEXT UNIQUE NOT NULL,  -- App login email (NextAuth)
  created_at  TEXT NOT NULL
);

-- One row per connected email source per user
-- provider: 'outlook' | 'gmail' | 'imap' | ...
CREATE TABLE source_tokens (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL REFERENCES users(id),
  provider          TEXT NOT NULL,            -- e.g. 'outlook'
  provider_email    TEXT NOT NULL,            -- The connected account address
  access_token_enc  TEXT NOT NULL,            -- AES-256 encrypted
  refresh_token_enc TEXT NOT NULL,            -- AES-256 encrypted
  expires_at        TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  UNIQUE(user_id, provider)                   -- One source per provider per user (v1)
);

-- One row per connected destination per user
-- provider: 'telegram' | 'teams' | 'slack' | 'email' | ...
CREATE TABLE destination_config (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id),
  provider    TEXT NOT NULL,                  -- e.g. 'telegram'
  config_enc  TEXT NOT NULL,                  -- AES-256 encrypted JSON (chat_id, webhook, etc.)
  created_at  TEXT NOT NULL,
  UNIQUE(user_id, provider)                   -- One destination per provider per user (v1)
);

-- Digest preferences and schedule per user
CREATE TABLE digest_settings (
  user_id       TEXT PRIMARY KEY REFERENCES users(id),
  digest_prefs  TEXT NOT NULL,                -- Free-text LLM prompt instructions
  schedule      TEXT NOT NULL DEFAULT 'morning',  -- 'morning' | 'evening' | 'both'
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_run_at   TEXT,
  last_email_id TEXT                          -- For dedup across runs
);

-- Audit log of every digest run
CREATE TABLE digest_runs (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id),
  source       TEXT NOT NULL,                 -- e.g. 'outlook'
  destination  TEXT NOT NULL,                 -- e.g. 'telegram'
  run_at       TEXT NOT NULL,
  email_count  INTEGER NOT NULL,
  status       TEXT NOT NULL,                 -- 'success' | 'error' | 'empty'
  error_msg    TEXT,
  tokens_used  INTEGER
);
```

---

### Database Backup — S3

**Strategy:** Daily cron on Lightsail copies the SQLite file to S3.

```bash
# /etc/cron.d/db-backup  (runs at 3am UTC daily)
0 3 * * * appuser /usr/local/bin/backup-db.sh

# /usr/local/bin/backup-db.sh
#!/bin/bash
set -e
DATE=$(date +%Y-%m-%d)
DB=/var/lib/email-summary-bot/db.sqlite
BUCKET=s3://your-backup-bucket/email-summary-bot

sqlite3 "$DB" ".backup /tmp/db-backup-$DATE.sqlite"
aws s3 cp /tmp/db-backup-$DATE.sqlite "$BUCKET/db-$DATE.sqlite"
rm /tmp/db-backup-$DATE.sqlite
echo "Backup complete: db-$DATE.sqlite"
```

Using `sqlite3 .backup` (not a raw file copy) ensures a consistent snapshot
even if a write is in progress. Set an S3 lifecycle rule to delete backups
older than 30 days.

**Optional upgrade:** [Litestream](https://litestream.io/) for continuous
WAL-based replication to S3 with point-in-time recovery — worth adding if
digest history becomes valuable.

---

### Summarization — Claude API (claude-haiku-4-5)

**Why Haiku:** Cheapest capable model. At ~20K tokens per digest, cost is ~$0.001/digest.
20 users × 2 digests/day × 30 days = **~$1.20/month**.

**Prompt architecture:**

The prompt has two layers:

1. **System prompt** (fixed) — instructs the model on output format and structure.
2. **User prefs** (per-user, editable in the UI) — natural language that personalizes
   urgency rules, todo detection, grouping, and tone.

The summarizer is source-agnostic: it receives a list of `EmailMessage` objects
regardless of whether they came from Outlook or Gmail.

**Default user prefs:**
> "Flag as urgent if someone is waiting on my response or there's a deadline mentioned.
> Create a todo if I owe someone something or have an action item. Group emails by
> inferred project or topic if you can determine one; otherwise group by sender domain."

**System prompt template:**
```
You are an intelligent email digest assistant for {{user_email}}.

USER PREFERENCES:
{{digest_prefs}}

Given the following emails (JSON), produce a structured digest with:
1. URGENT — emails needing action today (sorted by urgency)
2. ACTION REQUIRED — emails needing a response but not urgent
3. FYI — informational, no action needed
4. TODO LIST — a deduplicated list of action items the user needs to take

For each email include:
- Subject and sender
- One-sentence summary
- Why it's in this category
- Suggested reply or action (if applicable)

Output ONLY valid JSON matching this schema:
{
  "urgent": [...],
  "action_required": [...],
  "fyi": [...],
  "todos": [{"item": str, "source_email": str}]
}

Emails:
{{emails_json}}
```

---

### Source: Outlook — MS Graph API

**Why not MCP:** MCP is for interactive, real-time agentic tool use.
This app uses scheduled batch reads — a direct REST call is simpler and has
no extra infrastructure.

**OAuth2 flow:**
1. User visits `/onboard` → frontend calls `GET /auth/outlook/url`
2. Backend generates Microsoft OAuth consent URL (scopes: `Mail.Read`, `offline_access`)
3. User consents → Microsoft redirects to `POST /auth/outlook/callback`
4. Backend exchanges code for tokens, encrypts with AES-256, stores in `source_tokens`
5. Access tokens refreshed automatically before each Graph API call

**Email fetch:**
```
GET https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages
  ?$filter=receivedDateTime ge {last_run_at}
  &$select=id,subject,from,bodyPreview,receivedDateTime,isRead,conversationId,hasAttachments
  &$top=100
  &$orderby=receivedDateTime desc
```

Only `bodyPreview` (first ~255 chars) is sent to the LLM by default.
Full body is an opt-in setting stored in `digest_settings`.

---

### Destination: Telegram

**Setup per user:**
1. User messages `@YourBot` with `/start`
2. Telegram POSTs to `POST /destinations/telegram/webhook`
3. Backend captures `chat_id`, encrypts and stores in `destination_config`

**Supported bot commands:**
| Command | Action |
|---|---|
| `/start` | Register chat, show welcome message |
| `/digest` | Trigger an immediate digest |
| `/pause` | Pause scheduled digests |
| `/resume` | Resume scheduled digests |
| `/status` | Show last run time and email count |

**Message format:**
```
📬 *Your Morning Digest* — 12 emails

🔴 *URGENT* (2)
• [Re: Contract renewal] Alice @ Legal — deadline today. Reply needed.
• [Budget approval] Finance team — waiting on your sign-off.

🟡 *ACTION REQUIRED* (4)
...

📋 *TODO*
• Reply to Alice re: contract renewal
• Sign off on Q3 budget
```

Messages are split at 4096 chars (Telegram limit) and sent as numbered parts.

---

### Scheduler — GitHub Actions

**Why GitHub Actions:** Free, no extra infra, cron syntax, easy secrets management.
Scheduling logic lives in the repo, not on the server.

```yaml
# .github/workflows/digest.yml
on:
  schedule:
    - cron: '0 7 * * *'    # 7am UTC — morning digest
    - cron: '0 17 * * *'   # 5pm UTC — evening digest
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

The backend validates `X-Cron-Secret` and runs digests for all eligible users,
iterating over each user's configured sources and destinations.

---

### Server Setup — AWS Lightsail

**Instance:** Smallest Lightsail Linux instance (~$3.50–5/mo).
FastAPI + SQLite + nginx fit comfortably within 512MB RAM.

**nginx config:**
```nginx
server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$host$request_uri;
}
```

**systemd service** (`/etc/systemd/system/email-summary-bot.service`):
```ini
[Unit]
Description=email-summary-bot FastAPI backend
After=network.target

[Service]
User=appuser
WorkingDirectory=/home/appuser/email-summary-bot/backend
EnvironmentFile=/home/appuser/email-summary-bot/.env
ExecStart=/home/appuser/email-summary-bot/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Security Considerations

- **Token encryption:** All OAuth tokens (source and destination) encrypted with AES-256
  (`cryptography.fernet`) before storage. Encryption key in `.env`, never in DB or repo.
- **Cron auth:** `X-Cron-Secret` header on `/digest/run` — returns 403 if missing/wrong.
- **No full email body by default:** Only `bodyPreview` sent to LLM.
- **HTTPS:** nginx + Certbot handles TLS. Port 80 redirects to 443.
- **Firewall:** Lightsail firewall: ports 22, 80, 443 only.
- **DB permissions:** SQLite file owned by `appuser`, mode `600`.
- **Secrets:** All in `.env` on server only. Never committed. `.env.example` documents required vars.

---

## Environment Variables

```bash
# Backend (.env — on Lightsail only, never committed)
DB_PATH=/var/lib/email-summary-bot/db.sqlite
TOKEN_ENCRYPTION_KEY=...        # 32-byte hex: openssl rand -hex 32
CRON_SECRET=...                 # Random secret: openssl rand -hex 24
ANTHROPIC_API_KEY=sk-ant-...
FRONTEND_URL=https://your-app.vercel.app

# Outlook (MS Graph)
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
MS_REDIRECT_URI=https://api.yourdomain.com/auth/outlook/callback

# Telegram
TELEGRAM_BOT_TOKEN=...

# Future sources/destinations — add here as implemented
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...
# SLACK_WEBHOOK_URL=...

# Frontend (.env.local — Vercel environment variables)
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXTAUTH_SECRET=...
NEXTAUTH_URL=https://your-app.vercel.app
```

---

## Tech Stack Summary

| Layer | Technology | Hosting | Cost |
|---|---|---|---|
| Frontend | Next.js 14 | Vercel free tier | $0 |
| Backend | FastAPI (Python 3.11) | AWS Lightsail | ~$4/mo |
| Database | SQLite (local file) | Same Lightsail instance | $0 |
| DB Backup | awscli + S3 | AWS S3 (~1 MB/day) | ~$0.01/mo |
| LLM | Claude Haiku (Anthropic API) | Anthropic | ~$1/mo |
| Scheduler | GitHub Actions cron | GitHub free | $0 |
| Source (v1) | MS Graph API (Outlook) | Microsoft | $0 |
| Destination (v1) | Telegram Bot API | Telegram | $0 |
| **Total** | | | **~$5/month** |
