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
  account_type      TEXT NOT NULL DEFAULT 'personal',  -- 'personal' | 'work'
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
  digest_prefs  TEXT NOT NULL DEFAULT 'Flag as urgent if someone is waiting on my response or there is a deadline mentioned. Create a todo if I owe someone something or have an action item. Group emails by inferred project or topic if you can determine one; otherwise group by sender domain.',
  schedule      TEXT NOT NULL DEFAULT 'morning',  -- 'morning' | 'evening' | 'both'
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_run_at   TEXT,                         -- NULL for new users; treated as 24h ago on first run
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

-- Short-lived codes for linking a Telegram chat_id to an app user
-- Created when user clicks "Connect Telegram"; consumed when /start <code> is received
CREATE TABLE telegram_link_codes (
  code       TEXT PRIMARY KEY,               -- 6-char alphanumeric, e.g. 'A3K9PX'
  user_id    TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL                   -- 10 minutes after created_at
);
