"""Tests for the aiosqlite query layer in db.py."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _apply_schema(db_path: str) -> None:
    import sqlite3
    import pathlib
    schema = pathlib.Path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
    ).read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


class TestDBSchema(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self._db_path = self._tmp.name
        self._tmp.close()
        _apply_schema(self._db_path)
        os.environ["DB_PATH"] = self._db_path

    def tearDown(self) -> None:
        os.unlink(self._db_path)

    async def test_all_tables_exist(self) -> None:
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ) as cursor:
                tables = {row[0] for row in await cursor.fetchall()}
        expected = {
            "users",
            "source_tokens",
            "destination_config",
            "digest_settings",
            "digest_runs",
            "telegram_link_codes",
        }
        self.assertEqual(tables, expected)

    async def test_upsert_and_get_user(self) -> None:
        from db import get_user_by_id, upsert_user
        await upsert_user("user-1", "test@example.com", "2026-01-01T00:00:00Z")
        row = await get_user_by_id("user-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "test@example.com")

    async def test_get_user_returns_none_for_unknown(self) -> None:
        from db import get_user_by_id
        row = await get_user_by_id("nonexistent-id")
        self.assertIsNone(row)

    async def test_upsert_user_is_idempotent(self) -> None:
        from db import get_user_by_id, upsert_user
        await upsert_user("user-2", "a@a.com", "2026-01-01T00:00:00Z")
        await upsert_user("user-2", "a@a.com", "2026-01-01T00:00:00Z")  # no error
        row = await get_user_by_id("user-2")
        self.assertIsNotNone(row)

    async def test_get_source_token_returns_none_when_absent(self) -> None:
        from db import get_source_token
        row = await get_source_token("user-99", "outlook")
        self.assertIsNone(row)

    async def test_upsert_and_get_source_token(self) -> None:
        from db import get_source_token, upsert_source_token, upsert_user
        await upsert_user("user-3", "b@b.com", "2026-01-01T00:00:00Z")
        await upsert_source_token(
            token_id="tok-1",
            user_id="user-3",
            provider="outlook",
            provider_email="b@outlook.com",
            access_token_enc="enc-access",
            refresh_token_enc="enc-refresh",
            expires_at="2026-12-31T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )
        row = await get_source_token("user-3", "outlook")
        self.assertIsNotNone(row)
        self.assertEqual(row["provider_email"], "b@outlook.com")

    async def test_delete_source_token(self) -> None:
        from db import delete_source_token, get_source_token, upsert_source_token, upsert_user
        await upsert_user("user-4", "c@c.com", "2026-01-01T00:00:00Z")
        await upsert_source_token(
            token_id="tok-2",
            user_id="user-4",
            provider="outlook",
            provider_email="c@outlook.com",
            access_token_enc="enc",
            refresh_token_enc="enc",
            expires_at="2026-12-31T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )
        await delete_source_token("user-4", "outlook")
        row = await get_source_token("user-4", "outlook")
        self.assertIsNone(row)

    async def test_upsert_and_get_digest_settings(self) -> None:
        from db import get_digest_settings, upsert_digest_settings, upsert_user
        await upsert_user("user-5", "d@d.com", "2026-01-01T00:00:00Z")
        await upsert_digest_settings("user-5")
        row = await get_digest_settings("user-5")
        self.assertIsNotNone(row)
        self.assertEqual(row["schedule"], "morning")
        self.assertEqual(row["enabled"], 1)

    async def test_telegram_link_code_insert_and_fetch(self) -> None:
        from db import get_telegram_link_code, insert_telegram_link_code, upsert_user
        await upsert_user("user-6", "e@e.com", "2026-01-01T00:00:00Z")
        await insert_telegram_link_code(
            code="A1B2C3",
            user_id="user-6",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-01T00:10:00Z",
        )
        row = await get_telegram_link_code("A1B2C3")
        self.assertIsNotNone(row)
        self.assertEqual(row["user_id"], "user-6")

    async def test_telegram_link_code_delete(self) -> None:
        from db import delete_telegram_link_code, get_telegram_link_code, insert_telegram_link_code, upsert_user
        await upsert_user("user-7", "f@f.com", "2026-01-01T00:00:00Z")
        await insert_telegram_link_code(
            code="X9Y8Z7",
            user_id="user-7",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-01T00:10:00Z",
        )
        await delete_telegram_link_code("X9Y8Z7")
        row = await get_telegram_link_code("X9Y8Z7")
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
