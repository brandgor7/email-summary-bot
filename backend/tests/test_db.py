"""Tests for the aiosqlite query layer in db.py."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _apply_schema(db_path: str) -> None:
    import pathlib
    import sqlite3
    schema = pathlib.Path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
    ).read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


class TestDBSchema(unittest.IsolatedAsyncioTestCase):
    # One temp file shared across all tests in this class — created once in setUpClass.
    _db_path: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

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
        await upsert_user("u-get", "get@example.com", "2026-01-01T00:00:00Z")
        row = await get_user_by_id("u-get")
        self.assertIsNotNone(row)
        self.assertEqual(row["email"], "get@example.com")

    async def test_get_user_returns_none_for_unknown(self) -> None:
        from db import get_user_by_id
        row = await get_user_by_id("nonexistent-id")
        self.assertIsNone(row)

    async def test_upsert_user_is_idempotent(self) -> None:
        from db import get_user_by_id, upsert_user
        await upsert_user("u-idem", "idem@example.com", "2026-01-01T00:00:00Z")
        await upsert_user("u-idem", "idem@example.com", "2026-01-01T00:00:00Z")
        row = await get_user_by_id("u-idem")
        self.assertIsNotNone(row)

    async def test_get_source_token_returns_none_when_absent(self) -> None:
        from db import get_source_token
        row = await get_source_token("u-absent", "outlook")
        self.assertIsNone(row)

    async def test_upsert_and_get_source_token(self) -> None:
        from db import get_source_token, upsert_source_token, upsert_user
        await upsert_user("u-tok", "tok@example.com", "2026-01-01T00:00:00Z")
        await upsert_source_token(
            token_id="tok-a",
            user_id="u-tok",
            provider="outlook",
            provider_email="tok@outlook.com",
            access_token_enc="enc-access",
            refresh_token_enc="enc-refresh",
            expires_at="2026-12-31T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )
        row = await get_source_token("u-tok", "outlook")
        self.assertIsNotNone(row)
        self.assertEqual(row["provider_email"], "tok@outlook.com")

    async def test_delete_source_token(self) -> None:
        from db import delete_source_token, get_source_token, upsert_source_token, upsert_user
        await upsert_user("u-del", "del@example.com", "2026-01-01T00:00:00Z")
        await upsert_source_token(
            token_id="tok-b",
            user_id="u-del",
            provider="outlook",
            provider_email="del@outlook.com",
            access_token_enc="enc",
            refresh_token_enc="enc",
            expires_at="2026-12-31T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )
        await delete_source_token("u-del", "outlook")
        row = await get_source_token("u-del", "outlook")
        self.assertIsNone(row)

    async def test_upsert_and_get_digest_settings(self) -> None:
        from db import get_digest_settings, upsert_digest_settings, upsert_user
        await upsert_user("u-ds", "ds@example.com", "2026-01-01T00:00:00Z")
        await upsert_digest_settings("u-ds")
        row = await get_digest_settings("u-ds")
        self.assertIsNotNone(row)
        self.assertEqual(row["schedule"], "morning")
        self.assertEqual(row["enabled"], 1)

    async def test_telegram_link_code_insert_and_fetch(self) -> None:
        from db import get_telegram_link_code, insert_telegram_link_code, upsert_user
        await upsert_user("u-tg", "tg@example.com", "2026-01-01T00:00:00Z")
        await insert_telegram_link_code(
            code="A1B2C3",
            user_id="u-tg",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-01T00:10:00Z",
        )
        row = await get_telegram_link_code("A1B2C3")
        self.assertIsNotNone(row)
        self.assertEqual(row["user_id"], "u-tg")

    async def test_telegram_link_code_delete(self) -> None:
        from db import delete_telegram_link_code, get_telegram_link_code, insert_telegram_link_code, upsert_user
        await upsert_user("u-tgd", "tgd@example.com", "2026-01-01T00:00:00Z")
        await insert_telegram_link_code(
            code="X9Y8Z7",
            user_id="u-tgd",
            created_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-01T00:10:00Z",
        )
        await delete_telegram_link_code("X9Y8Z7")
        row = await get_telegram_link_code("X9Y8Z7")
        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
