"""Unit tests for /destinations/* routes — link-code, status, webhook, disconnect."""
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_SECRET = "test-nextauth-secret"
_WEBHOOK_SECRET = "test-webhook-secret"

os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
os.environ["TELEGRAM_WEBHOOK_SECRET"] = _WEBHOOK_SECRET
os.environ["TELEGRAM_BOT_USERNAME"] = "@TestBot"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost/callback")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import jwt
from starlette.testclient import TestClient

from main import app

_WEBHOOK_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": _WEBHOOK_SECRET}


def _valid_token(sub: str = "dest-test-user") -> str:
    return jwt.encode(
        {"sub": sub, "exp": int(time.time()) + 3600},
        _TEST_SECRET,
        algorithm="HS256",
    )


def _apply_schema(db_path: str) -> None:
    schema = pathlib.Path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
    ).read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


def _insert_user(db_path: str, user_id: str, email: str = "") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
        [user_id, email or f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
    )
    conn.commit()
    conn.close()


def _telegram_update(chat_id: int, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": chat_id},
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "date": int(time.time()),
        },
    }


# ── /destinations/telegram/link-code ───────────────────────────────────────

class TestLinkCode(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)
        cls.user_id = "link-code-user"
        _insert_user(cls.db_path, cls.user_id)
        cls.headers = {"Authorization": f"Bearer {_valid_token(sub=cls.user_id)}"}

    def test_returns_code_and_bot_username(self) -> None:
        response = self.client.post("/destinations/telegram/link-code", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("code", body)
        self.assertIn("bot_username", body)
        self.assertEqual(body["bot_username"], "@TestBot")

    def test_code_is_6_chars_alphanumeric_uppercase(self) -> None:
        response = self.client.post("/destinations/telegram/link-code", headers=self.headers)
        code = response.json()["code"]
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isupper() or code.isalnum())
        import re
        self.assertRegex(code, r"^[A-Z0-9]{6}$")

    def test_requires_auth(self) -> None:
        response = self.client.post("/destinations/telegram/link-code")
        self.assertEqual(response.status_code, 401)

    def test_code_stored_in_db(self) -> None:
        response = self.client.post("/destinations/telegram/link-code", headers=self.headers)
        code = response.json()["code"]
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM telegram_link_codes WHERE code = ?", [code]
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_code_expires_in_10_minutes(self) -> None:
        response = self.client.post("/destinations/telegram/link-code", headers=self.headers)
        code = response.json()["code"]
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT expires_at FROM telegram_link_codes WHERE code = ?", [code]
        ).fetchone()
        conn.close()
        expires_at = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        delta = expires_at - now
        self.assertGreater(delta.total_seconds(), 9 * 60)
        self.assertLessEqual(delta.total_seconds(), 11 * 60)


# ── /destinations/telegram/status ──────────────────────────────────────────

class TestTelegramStatus(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)

    def test_returns_linked_false_when_no_config(self) -> None:
        user_id = "status-unlinked"
        _insert_user(self.db_path, user_id)
        headers = {"Authorization": f"Bearer {_valid_token(sub=user_id)}"}
        response = self.client.get("/destinations/telegram/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"linked": False})

    def test_returns_linked_true_after_connecting(self) -> None:
        from services.destinations.telegram import TelegramDestination
        import asyncio

        user_id = "status-linked"
        _insert_user(self.db_path, user_id)
        asyncio.run(TelegramDestination().connect(user_id, {"chat_id": 8888}))

        headers = {"Authorization": f"Bearer {_valid_token(sub=user_id)}"}
        response = self.client.get("/destinations/telegram/status", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"linked": True})

    def test_requires_auth(self) -> None:
        response = self.client.get("/destinations/telegram/status")
        self.assertEqual(response.status_code, 401)


# ── /destinations/telegram/webhook ─────────────────────────────────────────

class TestWebhookAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_403_without_secret_header(self) -> None:
        response = self.client.post(
            "/destinations/telegram/webhook",
            json=_telegram_update(1, "/status"),
        )
        self.assertEqual(response.status_code, 403)

    def test_403_with_wrong_secret(self) -> None:
        response = self.client.post(
            "/destinations/telegram/webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            json=_telegram_update(1, "/status"),
        )
        self.assertEqual(response.status_code, 403)

    def test_200_with_correct_secret(self) -> None:
        with patch(
            "routers.destinations.send_telegram_message", new_callable=AsyncMock
        ):
            response = self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(1, "/status"),
            )
        self.assertEqual(response.status_code, 200)

    def test_update_without_message_field_is_ok(self) -> None:
        response = self.client.post(
            "/destinations/telegram/webhook",
            headers=_WEBHOOK_HEADERS,
            json={"update_id": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})


class TestWebhookStart(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)

    def _insert_link_code(self, code: str, user_id: str, expired: bool = False) -> None:
        now = datetime.now(timezone.utc)
        delta = timedelta(minutes=-5) if expired else timedelta(minutes=10)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [user_id, f"{user_id}@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.execute(
            "INSERT OR REPLACE INTO telegram_link_codes (code, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            [code, user_id, now.isoformat(), (now + delta).isoformat()],
        )
        conn.commit()
        conn.close()

    def test_valid_code_links_chat_and_stores_config(self) -> None:
        user_id = "start-user-1"
        self._insert_link_code("VALID1", user_id)

        sent: list[dict] = []

        async def fake_send(chat_id, text):
            sent.append({"chat_id": chat_id, "text": text})

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            response = self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(111222, "/start VALID1"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Connected" in m["text"] for m in sent))

        # Config should now be in DB
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT config_enc FROM destination_config WHERE user_id = ? AND provider = 'telegram'",
            [user_id],
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_valid_code_is_consumed(self) -> None:
        user_id = "start-user-2"
        self._insert_link_code("VALID2", user_id)

        with patch("routers.destinations.send_telegram_message", new_callable=AsyncMock):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(333444, "/start VALID2"),
            )

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM telegram_link_codes WHERE code = 'VALID2'"
        ).fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_invalid_code_sends_error_reply(self) -> None:
        sent: list[str] = []

        async def fake_send(chat_id, text):
            sent.append(text)

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(555, "/start BADCOD"),
            )

        self.assertTrue(any("invalid" in m.lower() for m in sent))

    def test_expired_code_sends_expired_reply(self) -> None:
        user_id = "start-user-expired"
        self._insert_link_code("EXPRD1", user_id, expired=True)

        sent: list[str] = []

        async def fake_send(chat_id, text):
            sent.append(text)

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(666, "/start EXPRD1"),
            )

        self.assertTrue(any("expired" in m.lower() for m in sent))

    def test_start_without_code_sends_instructions(self) -> None:
        sent: list[str] = []

        async def fake_send(chat_id, text):
            sent.append(text)

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(777, "/start"),
            )

        self.assertTrue(len(sent) > 0)


class TestWebhookCommands(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)

        # Set up a linked user
        cls.user_id = "cmd-user-1"
        cls.chat_id = 123456789
        conn = sqlite3.connect(cls.db_path)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, ?)",
            [cls.user_id, "cmd@test.com", "2025-01-01T00:00:00+00:00"],
        )
        conn.commit()
        conn.close()

        from services.destinations.telegram import TelegramDestination
        import asyncio
        asyncio.run(TelegramDestination().connect(cls.user_id, {"chat_id": cls.chat_id}))

    def test_pause_sets_enabled_false(self) -> None:
        with patch("routers.destinations.send_telegram_message", new_callable=AsyncMock):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(self.chat_id, "/pause"),
            )

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT enabled FROM digest_settings WHERE user_id = ?", [self.user_id]
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 0)

    def test_resume_sets_enabled_true(self) -> None:
        # First pause, then resume
        with patch("routers.destinations.send_telegram_message", new_callable=AsyncMock):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(self.chat_id, "/pause"),
            )
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(self.chat_id, "/resume"),
            )

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT enabled FROM digest_settings WHERE user_id = ?", [self.user_id]
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)

    def test_status_sends_reply(self) -> None:
        sent: list[str] = []

        async def fake_send(chat_id, text):
            sent.append(text)

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(self.chat_id, "/status"),
            )

        self.assertTrue(len(sent) > 0)
        self.assertTrue(any("Status" in m for m in sent))

    def test_unlinked_chat_gets_instructions(self) -> None:
        unlinked_chat = 987654321
        sent: list[str] = []

        async def fake_send(chat_id, text):
            sent.append(text)

        with patch("routers.destinations.send_telegram_message", side_effect=fake_send):
            self.client.post(
                "/destinations/telegram/webhook",
                headers=_WEBHOOK_HEADERS,
                json=_telegram_update(unlinked_chat, "/status"),
            )

        self.assertTrue(any("web app" in m.lower() or "not linked" in m.lower() for m in sent))


# ── /destinations/{type}/disconnect ────────────────────────────────────────

class TestDisconnectDestination(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)

    def test_disconnect_telegram_removes_config(self) -> None:
        user_id = "disconnect-route-user"
        _insert_user(self.db_path, user_id)
        from services.destinations.telegram import TelegramDestination
        import asyncio
        asyncio.run(TelegramDestination().connect(user_id, {"chat_id": 11111}))

        headers = {"Authorization": f"Bearer {_valid_token(sub=user_id)}"}
        response = self.client.delete("/destinations/telegram/disconnect", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"disconnected": "telegram"})

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM destination_config WHERE user_id = ?", [user_id]
        ).fetchone()
        conn.close()
        self.assertIsNone(row)

    def test_disconnect_unknown_provider_returns_404(self) -> None:
        headers = {"Authorization": f"Bearer {_valid_token()}"}
        response = self.client.delete("/destinations/nonexistent/disconnect", headers=headers)
        self.assertEqual(response.status_code, 404)

    def test_disconnect_requires_auth(self) -> None:
        response = self.client.delete("/destinations/telegram/disconnect")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
