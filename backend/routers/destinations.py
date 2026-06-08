import logging
import os
import random
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

import db
from dependencies import get_current_user
from services import summarizer
from services.destinations.telegram import TelegramDestination, send_telegram_message
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS

router = APIRouter(prefix="/destinations", tags=["destinations"])
logger = logging.getLogger(__name__)

_telegram = TelegramDestination()


def _generate_link_code() -> str:
    """Generate a 6-char alphanumeric one-time code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ── Telegram-specific routes ────────────────────────────────────────────────

@router.post("/telegram/link-code")
async def telegram_link_code(user: dict = Depends(get_current_user)) -> dict:
    """Generate a one-time code so the user can link their Telegram chat."""
    user_id: str = user["sub"]
    code = _generate_link_code()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)
    await db.insert_telegram_link_code(code, user_id, now.isoformat(), expires_at.isoformat())
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "@YourBot")
    return {"code": code, "bot_username": bot_username}


@router.get("/telegram/status")
async def telegram_status(user: dict = Depends(get_current_user)) -> dict:
    """Return whether the current user has a linked Telegram chat."""
    user_id: str = user["sub"]
    config = await db.get_destination_config(user_id, "telegram")
    return {"linked": config is not None}


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Receive Telegram updates — validates webhook secret before any processing."""
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected or x_telegram_bot_api_secret_token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")

    body = await request.json()
    message = body.get("message")
    if not message:
        return {"ok": True}

    chat_id: int = message["chat"]["id"]
    text: str = message.get("text", "")

    try:
        if text.startswith("/start"):
            await _handle_start(chat_id, text)
        elif text.startswith("/digest"):
            await _handle_digest(chat_id)
        elif text.startswith("/pause"):
            await _handle_pause(chat_id)
        elif text.startswith("/resume"):
            await _handle_resume(chat_id)
        elif text.startswith("/status"):
            await _handle_status(chat_id)
    except Exception:
        logger.exception("Error processing webhook command %r for chat %d", text, chat_id)

    return {"ok": True}


async def _handle_start(chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await send_telegram_message(
            chat_id, "Please send `/start <code>` with the code shown in the web app."
        )
        return

    code = parts[1].strip()
    now = datetime.now(timezone.utc)
    row = await db.get_telegram_link_code(code)

    if not row:
        await send_telegram_message(
            chat_id, "❌ That code is invalid. Generate a new one in the web app."
        )
        return

    expires_at = datetime.fromisoformat(row["expires_at"])
    if now >= expires_at:
        await db.delete_telegram_link_code(code)
        await send_telegram_message(
            chat_id, "❌ That code has expired. Generate a new one in the web app."
        )
        return

    user_id: str = row["user_id"]
    await _telegram.connect(user_id, {"chat_id": chat_id})
    await db.delete_telegram_link_code(code)
    await send_telegram_message(chat_id, "✅ Connected! You'll receive your digests here.")


async def _handle_digest(chat_id: int) -> None:
    user_id = await _telegram.get_user_id_for_chat(chat_id)
    if not user_id:
        await send_telegram_message(
            chat_id, "Not linked. Visit the web app to connect your Telegram account."
        )
        return

    settings = await db.get_digest_settings(user_id)
    since = (
        datetime.fromisoformat(settings["last_run_at"])
        if settings and settings["last_run_at"]
        else datetime.now(timezone.utc) - timedelta(hours=24)
    )

    all_emails = []
    for row in await db.get_all_source_tokens_for_user(user_id):
        provider = SOURCE_PROVIDERS.get(row["provider"])
        if provider:
            emails = await provider.fetch_emails(user_id, since=since)
            all_emails.extend(emails)

    if not all_emails:
        await send_telegram_message(chat_id, "No new emails since your last digest. 🎉")
        return

    result = await summarizer.summarize(user_id, all_emails)
    await _telegram.send_digest(user_id, result["digest"])


async def _handle_pause(chat_id: int) -> None:
    user_id = await _telegram.get_user_id_for_chat(chat_id)
    if not user_id:
        await send_telegram_message(
            chat_id, "Not linked. Visit the web app to connect your Telegram account."
        )
        return
    await db.upsert_digest_settings(user_id, enabled=0)
    await send_telegram_message(
        chat_id, "⏸ Scheduled digests paused. Send /resume to turn them back on."
    )


async def _handle_resume(chat_id: int) -> None:
    user_id = await _telegram.get_user_id_for_chat(chat_id)
    if not user_id:
        await send_telegram_message(
            chat_id, "Not linked. Visit the web app to connect your Telegram account."
        )
        return
    await db.upsert_digest_settings(user_id, enabled=1)
    await send_telegram_message(chat_id, "▶️ Scheduled digests resumed.")


async def _handle_status(chat_id: int) -> None:
    user_id = await _telegram.get_user_id_for_chat(chat_id)
    if not user_id:
        await send_telegram_message(
            chat_id, "Not linked. Visit the web app to connect your Telegram account."
        )
        return
    settings = await db.get_digest_settings(user_id)
    if not settings:
        await send_telegram_message(chat_id, "No digest settings found.")
        return
    last_run = settings["last_run_at"] or "Never"
    enabled_str = "enabled ✅" if settings["enabled"] else "paused ⏸"
    await send_telegram_message(chat_id, f"Status: {enabled_str}\nLast digest: {last_run}")


# ── Generic destination routes ───────────────────────────────────────────────

@router.post("/{destination_type}/connect")
async def connect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Connect a destination provider (Telegram uses the link-code flow instead)."""
    if not DESTINATION_PROVIDERS.get(destination_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Use POST /destinations/telegram/link-code for Telegram; other providers not yet implemented",
    )


@router.delete("/{destination_type}/disconnect")
async def disconnect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Disconnect a destination provider."""
    provider = DESTINATION_PROVIDERS.get(destination_type)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    user_id: str = user["sub"]
    await provider.disconnect(user_id)
    return {"disconnected": destination_type}
