"""Telegram Bot API destination provider."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import certifi
import httpx

import db
import services.token_store as token_store
from services.destinations.base import DigestDestination

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_MAX_MESSAGE_LEN = 4096


class TelegramDestination(DigestDestination):

    async def connect(self, user_id: str, config: dict) -> None:
        """Encrypt and store chat_id in destination_config."""
        config_enc = token_store.encrypt(json.dumps(config))
        created_at = datetime.now(timezone.utc).isoformat()
        await db.upsert_destination_config(
            str(uuid.uuid4()), user_id, "telegram", config_enc, created_at
        )

    async def send_digest(self, user_id: str, digest: dict) -> None:
        """Format digest to Markdown and deliver via Telegram Bot API."""
        config = await self._load_config(user_id)
        chat_id = config["chat_id"]
        text = format_digest_markdown(digest)
        await send_telegram_message(chat_id, text)

    async def disconnect(self, user_id: str) -> None:
        """Remove destination config row."""
        await db.delete_destination_config(user_id, "telegram")

    async def send_notification(self, user_id: str, message: str) -> None:
        """Send a plain text message to the user's linked Telegram chat."""
        config = await self._load_config(user_id)
        await send_telegram_message(config["chat_id"], message)

    async def get_user_id_for_chat(self, chat_id: int) -> str | None:
        """Return the user_id linked to a Telegram chat_id by scanning all stored configs."""
        rows = await db.get_all_destination_configs_for_provider("telegram")
        for row in rows:
            try:
                config = json.loads(token_store.decrypt(row["config_enc"]))
                if config.get("chat_id") == chat_id:
                    return row["user_id"]
            except Exception:
                continue
        return None

    async def _load_config(self, user_id: str) -> dict:
        """Fetch and decrypt the Telegram config for a user."""
        row = await db.get_destination_config(user_id, "telegram")
        if not row:
            raise RuntimeError(f"No Telegram config for user {user_id}")
        return json.loads(token_store.decrypt(row["config_enc"]))


async def send_telegram_message(chat_id: int, text: str) -> None:
    """Send text to a Telegram chat, splitting at 4096 chars if needed."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    parts = _split_message(text)
    async with httpx.AsyncClient(verify=certifi.where()) as client:
        for i, part in enumerate(parts, 1):
            payload: dict = {"chat_id": chat_id, "text": part, "parse_mode": "Markdown"}
            if len(parts) > 1:
                payload["text"] = f"Part {i}/{len(parts)}:\n\n{part}"
            resp = await client.post(
                f"{_TELEGRAM_API}/bot{bot_token}/sendMessage", json=payload
            )
            resp.raise_for_status()


def format_digest_markdown(digest: dict) -> str:
    """Format a digest dict as a Telegram Markdown string."""
    urgent = digest.get("urgent", [])
    action_required = digest.get("action_required", [])
    fyi = digest.get("fyi", [])
    todos = digest.get("todos", [])

    total = len(urgent) + len(action_required) + len(fyi)
    lines = [f"📬 *Your Digest* — {total} email{'s' if total != 1 else ''}"]

    if urgent:
        lines.append(f"\n🔴 *URGENT* ({len(urgent)})")
        for e in urgent:
            lines.append(f"• {e['subject']} | {e['sender']} — {e['summary']}")
            if e.get("suggested_action"):
                lines.append(f"  ↳ {e['suggested_action']}")

    if action_required:
        lines.append(f"\n🟡 *ACTION REQUIRED* ({len(action_required)})")
        for e in action_required:
            lines.append(f"• {e['subject']} | {e['sender']} — {e['summary']}")
            if e.get("suggested_action"):
                lines.append(f"  ↳ {e['suggested_action']}")

    if fyi:
        lines.append(f"\nℹ️ *FYI* ({len(fyi)})")
        for e in fyi:
            lines.append(f"• {e['subject']} | {e['sender']} — {e['summary']}")

    if todos:
        lines.append("\n📋 *TODO*")
        for todo in todos:
            lines.append(f"• {todo['item']}")

    if total == 0:
        lines.append("\nNo new emails since your last digest. 🎉")

    return "\n".join(lines)


def _split_message(text: str) -> list[str]:
    """Split text into chunks of at most _MAX_MESSAGE_LEN chars, preferring newline boundaries."""
    if len(text) <= _MAX_MESSAGE_LEN:
        return [text]
    parts = []
    while text:
        if len(text) <= _MAX_MESSAGE_LEN:
            parts.append(text)
            break
        chunk = text[:_MAX_MESSAGE_LEN]
        split_at = chunk.rfind("\n")
        if split_at <= 0:
            split_at = _MAX_MESSAGE_LEN
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return parts
