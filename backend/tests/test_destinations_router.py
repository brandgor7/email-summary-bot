"""Unit tests for /destinations/* routes — connect, status, disconnect."""
import os
import pathlib
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_SECRET = "test-nextauth-secret"

os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost/callback")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import jwt
from starlette.testclient import TestClient

from main import app


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


# ── /destinations/telegram/connect ─────────────────────────────────────────

class TestTelegramConnect(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls.db_path = cls.tmp.name
        _apply_schema(cls.db_path)
        os.environ["DB_PATH"] = cls.db_path
        cls.client = TestClient(app)
        cls.user_id = "connect-test-user"
        _insert_user(cls.db_path, cls.user_id)
        cls.headers = {"Authorization": f"Bearer {_valid_token(sub=cls.user_id)}"}

    def test_connect_stores_chat_id(self) -> None:
        response = self.client.post(
            "/destinations/telegram/connect",
            json={"chat_id": "123456789"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"linked": True})
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM destination_config WHERE user_id = ? AND provider = 'telegram'",
            [self.user_id],
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_connect_accepts_negative_chat_id(self) -> None:
        user_id = "connect-negative-user"
        _insert_user(self.db_path, user_id)
        headers = {"Authorization": f"Bearer {_valid_token(sub=user_id)}"}
        response = self.client.post(
            "/destinations/telegram/connect",
            json={"chat_id": "-100987654321"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)

    def test_connect_rejects_non_numeric_chat_id(self) -> None:
        response = self.client.post(
            "/destinations/telegram/connect",
            json={"chat_id": "not-a-number"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_connect_requires_auth(self) -> None:
        response = self.client.post(
            "/destinations/telegram/connect",
            json={"chat_id": "123456789"},
        )
        self.assertEqual(response.status_code, 401)


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
