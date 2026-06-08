"""Unit tests for TelegramDestination and its helper functions."""
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("DB_PATH", ":memory:")

from services.destinations.telegram import (
    TelegramDestination,
    _split_message,
    format_digest_markdown,
)


def _apply_schema(db_path: str) -> None:
    schema = pathlib.Path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
    ).read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


def _sample_digest(
    urgent: list | None = None,
    action_required: list | None = None,
    fyi: list | None = None,
    todos: list | None = None,
) -> dict:
    return {
        "urgent": urgent or [],
        "action_required": action_required or [],
        "fyi": fyi or [],
        "todos": todos or [],
    }


def _urgent_item(subject="Urgent Email", sender="boss@corp.com", summary="Needs action now") -> dict:
    return {"subject": subject, "sender": sender, "summary": summary,
            "reason": "Time-sensitive", "suggested_action": "Reply immediately"}


def _fyi_item(subject="Newsletter", sender="news@sub.com", summary="Weekly roundup") -> dict:
    return {"subject": subject, "sender": sender, "summary": summary}


# ── format_digest_markdown ─────────────────────────────────────────────────

class TestFormatDigestMarkdown(unittest.TestCase):

    def test_shows_email_count_in_header(self) -> None:
        digest = _sample_digest(urgent=[_urgent_item()], fyi=[_fyi_item()])
        text = format_digest_markdown(digest)
        self.assertIn("2 emails", text)

    def test_singular_email_count(self) -> None:
        digest = _sample_digest(fyi=[_fyi_item()])
        text = format_digest_markdown(digest)
        self.assertIn("1 email", text)
        self.assertNotIn("1 emails", text)

    def test_urgent_section_present(self) -> None:
        digest = _sample_digest(urgent=[_urgent_item(subject="Contract Renewal")])
        text = format_digest_markdown(digest)
        self.assertIn("URGENT", text)
        self.assertIn("Contract Renewal", text)

    def test_action_required_section_present(self) -> None:
        item = {"subject": "Budget Approval", "sender": "finance@co.com",
                "summary": "Needs sign-off", "reason": "Action needed", "suggested_action": "Approve"}
        digest = _sample_digest(action_required=[item])
        text = format_digest_markdown(digest)
        self.assertIn("ACTION REQUIRED", text)
        self.assertIn("Budget Approval", text)

    def test_fyi_section_present(self) -> None:
        digest = _sample_digest(fyi=[_fyi_item(subject="Company Newsletter")])
        text = format_digest_markdown(digest)
        self.assertIn("FYI", text)
        self.assertIn("Company Newsletter", text)

    def test_todos_section_present(self) -> None:
        digest = _sample_digest(
            todos=[{"item": "Reply to Alice", "source_email": "alice@co.com"}]
        )
        text = format_digest_markdown(digest)
        self.assertIn("TODO", text)
        self.assertIn("Reply to Alice", text)

    def test_suggested_action_shown(self) -> None:
        item = _urgent_item()
        item["suggested_action"] = "Call Alice back"
        digest = _sample_digest(urgent=[item])
        text = format_digest_markdown(digest)
        self.assertIn("Call Alice back", text)

    def test_empty_digest_shows_no_new_emails(self) -> None:
        digest = _sample_digest()
        text = format_digest_markdown(digest)
        self.assertIn("No new emails", text)
        self.assertIn("0 emails", text)

    def test_absent_sections_not_shown(self) -> None:
        digest = _sample_digest(fyi=[_fyi_item()])
        text = format_digest_markdown(digest)
        self.assertNotIn("URGENT", text)
        self.assertNotIn("ACTION REQUIRED", text)
        self.assertNotIn("TODO", text)

    def test_returns_string(self) -> None:
        self.assertIsInstance(format_digest_markdown(_sample_digest()), str)

    def test_section_count_in_heading(self) -> None:
        digest = _sample_digest(urgent=[_urgent_item(), _urgent_item(subject="Also Urgent")])
        text = format_digest_markdown(digest)
        self.assertIn("*URGENT* (2)", text)

    def test_multiple_todos_all_present(self) -> None:
        todos = [
            {"item": "Reply to Alice", "source_email": "alice@co.com"},
            {"item": "Sign contract", "source_email": "legal@co.com"},
        ]
        text = format_digest_markdown(_sample_digest(todos=todos))
        self.assertIn("Reply to Alice", text)
        self.assertIn("Sign contract", text)


# ── _split_message ─────────────────────────────────────────────────────────

class TestSplitMessage(unittest.TestCase):

    def test_short_message_returns_single_part(self) -> None:
        text = "Hello World"
        parts = _split_message(text)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0], text)

    def test_exactly_at_limit_returns_single_part(self) -> None:
        text = "x" * 4096
        parts = _split_message(text)
        self.assertEqual(len(parts), 1)

    def test_long_message_splits_into_multiple_parts(self) -> None:
        line = "A" * 100 + "\n"
        text = line * 50  # 5050 chars — just over the 4096 limit
        parts = _split_message(text)
        self.assertGreater(len(parts), 1)

    def test_all_parts_within_limit(self) -> None:
        line = "B" * 100 + "\n"
        text = line * 100
        parts = _split_message(text)
        for part in parts:
            self.assertLessEqual(len(part), 4096)

    def test_splits_at_newline_not_mid_line(self) -> None:
        # 40 lines of 100 chars each — first split should be at a newline
        line = "C" * 99 + "\n"
        text = line * 50
        parts = _split_message(text)
        # Second part should not start mid-word (no leading newline from lstrip)
        self.assertFalse(parts[1].startswith("\n"))

    def test_very_long_line_without_newlines_splits_at_char_limit(self) -> None:
        text = "D" * 10000
        parts = _split_message(text)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 4096)

    def test_reconstructed_text_matches_original(self) -> None:
        line = "E" * 100 + "\n"
        original = line * 60
        parts = _split_message(original)
        # Joining with newline should recover the original (lstrip removes leading \n)
        reconstructed = "\n".join(parts)
        self.assertEqual(len(reconstructed), len(original) - original.count("\n\n"))


# ── TelegramDestination.connect / disconnect ───────────────────────────────

class TestTelegramDestinationConnect(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)

    def setUp(self) -> None:
        os.environ["DB_PATH"] = self.db_path

    async def test_stores_config_in_db(self) -> None:
        import db
        user_id = "connect-user-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 12345})

        row = await db.get_destination_config(user_id, "telegram")
        self.assertIsNotNone(row)

    async def test_config_is_encrypted_in_db(self) -> None:
        import db
        user_id = "connect-user-2"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        await TelegramDestination().connect(user_id, {"chat_id": 99999})
        row = await db.get_destination_config(user_id, "telegram")
        # Raw value must not contain the plaintext chat_id
        self.assertNotIn("99999", row["config_enc"])

    async def test_connect_overwrites_existing_config(self) -> None:
        import db
        user_id = "connect-user-3"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 111})
        await dest.connect(user_id, {"chat_id": 222})

        row = await db.get_destination_config(user_id, "telegram")
        from services import token_store
        config = json.loads(token_store.decrypt(row["config_enc"]))
        self.assertEqual(config["chat_id"], 222)


class TestTelegramDestinationDisconnect(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)

    def setUp(self) -> None:
        os.environ["DB_PATH"] = self.db_path

    async def test_removes_config_from_db(self) -> None:
        import db
        user_id = "disconnect-user-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 55555})
        await dest.disconnect(user_id)

        row = await db.get_destination_config(user_id, "telegram")
        self.assertIsNone(row)

    async def test_disconnect_nonexistent_is_silent(self) -> None:
        dest = TelegramDestination()
        # Should not raise
        await dest.disconnect("nonexistent-user")


# ── TelegramDestination.get_user_id_for_chat ──────────────────────────────

class TestGetUserIdForChat(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)

    def setUp(self) -> None:
        os.environ["DB_PATH"] = self.db_path

    async def test_returns_user_id_for_linked_chat(self) -> None:
        user_id = "lookup-user-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 777777})
        result = await dest.get_user_id_for_chat(777777)
        self.assertEqual(result, user_id)

    async def test_returns_none_for_unlinked_chat(self) -> None:
        dest = TelegramDestination()
        result = await dest.get_user_id_for_chat(999888777)
        self.assertIsNone(result)

    async def test_distinguishes_between_multiple_users(self) -> None:
        user_a = "lookup-user-a"
        user_b = "lookup-user-b"
        conn = sqlite3.connect(self.db_path)
        for uid in [user_a, user_b]:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
                [uid, f"{uid}@test.com", "2025-01-01T00:00:00+00:00"],
            )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_a, {"chat_id": 100001})
        await dest.connect(user_b, {"chat_id": 100002})

        self.assertEqual(await dest.get_user_id_for_chat(100001), user_a)
        self.assertEqual(await dest.get_user_id_for_chat(100002), user_b)


# ── TelegramDestination.send_digest ───────────────────────────────────────

class TestTelegramDestinationSendDigest(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)

    def setUp(self) -> None:
        os.environ["DB_PATH"] = self.db_path

    async def test_calls_telegram_api_sendmessage(self) -> None:
        user_id = "send-user-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 42})

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        digest = _sample_digest(fyi=[_fyi_item(subject="Meeting Notes")])
        with patch("services.destinations.telegram.httpx.AsyncClient", return_value=mock_client):
            await dest.send_digest(user_id, digest)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]
        self.assertEqual(payload["chat_id"], 42)
        self.assertIn("Meeting Notes", payload["text"])

    async def test_raises_when_no_config(self) -> None:
        dest = TelegramDestination()
        with self.assertRaises(RuntimeError):
            await dest.send_digest("user-without-config", _sample_digest())

    async def test_long_digest_splits_into_multiple_messages(self) -> None:
        user_id = "send-user-2"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        dest = TelegramDestination()
        await dest.connect(user_id, {"chat_id": 43})

        # Build a digest whose Markdown exceeds 4096 chars
        many_fyi = [
            {"subject": f"Newsletter {i}" + "x" * 80, "sender": f"news{i}@sub.com",
             "summary": "Weekly roundup " + "y" * 60}
            for i in range(40)
        ]
        digest = _sample_digest(fyi=many_fyi)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("services.destinations.telegram.httpx.AsyncClient", return_value=mock_client):
            await dest.send_digest(user_id, digest)

        self.assertGreater(mock_client.post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
