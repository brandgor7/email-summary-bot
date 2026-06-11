import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield an aiosqlite connection with row_factory set to aiosqlite.Row."""
    db_path = os.getenv("DB_PATH", "./dev.sqlite")
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn


async def get_user_by_id(user_id: str) -> aiosqlite.Row | None:
    """Fetch a user row by id."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE id = ?", [user_id]) as cursor:
            return await cursor.fetchone()


async def upsert_user(user_id: str, email: str, created_at: str) -> None:
    """Insert a user row if it doesn't exist."""
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, email, created_at],
        )
        await db.commit()


async def get_source_token(user_id: str, provider: str) -> aiosqlite.Row | None:
    """Fetch an encrypted source token row for a user/provider pair."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM source_tokens WHERE user_id = ? AND provider = ?",
            [user_id, provider],
        ) as cursor:
            return await cursor.fetchone()


async def upsert_source_token(
    token_id: str,
    user_id: str,
    provider: str,
    provider_email: str,
    access_token_enc: str,
    refresh_token_enc: str,
    expires_at: str,
    created_at: str,
    account_type: str = "personal",
) -> None:
    """Insert or replace a source token row."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO source_tokens
               (id, user_id, provider, provider_email, access_token_enc,
                refresh_token_enc, expires_at, created_at, account_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET
                 provider_email=excluded.provider_email,
                 access_token_enc=excluded.access_token_enc,
                 refresh_token_enc=excluded.refresh_token_enc,
                 expires_at=excluded.expires_at,
                 account_type=excluded.account_type""",
            [
                token_id, user_id, provider, provider_email,
                access_token_enc, refresh_token_enc, expires_at, created_at, account_type,
            ],
        )
        await db.commit()


async def delete_source_token(user_id: str, provider: str) -> None:
    """Remove a source token row."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM source_tokens WHERE user_id = ? AND provider = ?",
            [user_id, provider],
        )
        await db.commit()


async def get_destination_config(user_id: str, provider: str) -> aiosqlite.Row | None:
    """Fetch encrypted destination config for a user/provider pair."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM destination_config WHERE user_id = ? AND provider = ?",
            [user_id, provider],
        ) as cursor:
            return await cursor.fetchone()


async def upsert_destination_config(
    config_id: str, user_id: str, provider: str, config_enc: str, created_at: str
) -> None:
    """Insert or replace a destination config row."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO destination_config (id, user_id, provider, config_enc, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, provider) DO UPDATE SET config_enc=excluded.config_enc""",
            [config_id, user_id, provider, config_enc, created_at],
        )
        await db.commit()


async def delete_destination_config(user_id: str, provider: str) -> None:
    """Remove a destination config row."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM destination_config WHERE user_id = ? AND provider = ?",
            [user_id, provider],
        )
        await db.commit()


async def get_digest_settings(user_id: str) -> aiosqlite.Row | None:
    """Fetch digest settings for a user."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM digest_settings WHERE user_id = ?", [user_id]
        ) as cursor:
            return await cursor.fetchone()


async def upsert_digest_settings(
    user_id: str,
    digest_prefs: str | None = None,
    schedule: str | None = None,
    enabled: int | None = None,
) -> None:
    """Insert default digest settings or update specific fields."""
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO digest_settings (user_id) VALUES (?)", [user_id]
        )
        if digest_prefs is not None:
            await db.execute(
                "UPDATE digest_settings SET digest_prefs = ? WHERE user_id = ?",
                [digest_prefs, user_id],
            )
        if schedule is not None:
            await db.execute(
                "UPDATE digest_settings SET schedule = ? WHERE user_id = ?",
                [schedule, user_id],
            )
        if enabled is not None:
            await db.execute(
                "UPDATE digest_settings SET enabled = ? WHERE user_id = ?",
                [enabled, user_id],
            )
        await db.commit()


async def update_last_run(user_id: str, last_run_at: str, last_email_id: str | None) -> None:
    """Update last_run_at and last_email_id after a digest run."""
    async with get_db() as db:
        await db.execute(
            "UPDATE digest_settings SET last_run_at = ?, last_email_id = ? WHERE user_id = ?",
            [last_run_at, last_email_id, user_id],
        )
        await db.commit()


async def insert_digest_run(
    run_id: str,
    user_id: str,
    source: str,
    destination: str,
    run_at: str,
    email_count: int,
    status: str,
    error_msg: str | None,
    tokens_used: int | None,
) -> None:
    """Log a completed digest run."""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO digest_runs
               (id, user_id, source, destination, run_at, email_count, status, error_msg, tokens_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [run_id, user_id, source, destination, run_at, email_count, status, error_msg, tokens_used],
        )
        await db.commit()


async def get_telegram_link_code(code: str) -> aiosqlite.Row | None:
    """Fetch a Telegram link code row."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM telegram_link_codes WHERE code = ?", [code]
        ) as cursor:
            return await cursor.fetchone()


async def insert_telegram_link_code(
    code: str, user_id: str, created_at: str, expires_at: str
) -> None:
    """Insert a new Telegram link code."""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO telegram_link_codes (code, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            [code, user_id, created_at, expires_at],
        )
        await db.commit()


async def delete_telegram_link_code(code: str) -> None:
    """Delete a used or expired Telegram link code."""
    async with get_db() as db:
        await db.execute("DELETE FROM telegram_link_codes WHERE code = ?", [code])
        await db.commit()


async def get_all_destination_configs_for_provider(provider: str) -> list[aiosqlite.Row]:
    """Fetch all destination config rows for a given provider."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM destination_config WHERE provider = ?", [provider]
        ) as cursor:
            return await cursor.fetchall()


async def get_all_source_tokens_for_user(user_id: str) -> list[aiosqlite.Row]:
    """Fetch all source token rows for a user."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM source_tokens WHERE user_id = ?", [user_id]
        ) as cursor:
            return await cursor.fetchall()


async def get_all_destination_configs_for_user(user_id: str) -> list[aiosqlite.Row]:
    """Fetch all destination config rows for a user."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM destination_config WHERE user_id = ?", [user_id]
        ) as cursor:
            return await cursor.fetchall()


async def delete_expired_telegram_link_codes(now: str) -> None:
    """Delete telegram_link_codes rows where expires_at is in the past."""
    async with get_db() as conn:
        await conn.execute(
            "DELETE FROM telegram_link_codes WHERE expires_at < ?", [now]
        )
        await conn.commit()


async def get_admin_stats() -> dict:
    """Return aggregate digest run statistics per user and overall totals."""
    async with get_db() as conn:
        async with conn.execute(
            """
            SELECT
                user_id,
                COUNT(*) AS total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_runs,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_runs,
                SUM(CASE WHEN status = 'empty' THEN 1 ELSE 0 END) AS empty_runs,
                CAST(AVG(CAST(tokens_used AS REAL)) AS INTEGER) AS avg_tokens,
                MAX(run_at) AS last_run_at
            FROM digest_runs
            GROUP BY user_id
            ORDER BY user_id
            """
        ) as cursor:
            run_rows = await cursor.fetchall()

        async with conn.execute("SELECT COUNT(*) AS count FROM users") as cursor:
            user_count_row = await cursor.fetchone()

    per_user = [dict(row) for row in run_rows]
    total_runs = sum(r["total_runs"] for r in per_user)
    error_runs = sum(r["error_runs"] for r in per_user)
    success_runs = sum(r["success_runs"] for r in per_user)

    return {
        "user_count": user_count_row["count"] if user_count_row else 0,
        "total_runs": total_runs,
        "success_runs": success_runs,
        "error_runs": error_runs,
        "error_rate": round(error_runs / total_runs, 4) if total_runs > 0 else 0.0,
        "per_user": per_user,
    }


async def get_enabled_users_for_schedule(schedule_slot: str) -> list[aiosqlite.Row]:
    """Fetch all enabled users whose schedule matches the given slot ('morning', 'evening', 'both')."""
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM digest_settings WHERE enabled = 1 AND (schedule = ? OR schedule = 'both')",
            [schedule_slot],
        ) as cursor:
            return await cursor.fetchall()
