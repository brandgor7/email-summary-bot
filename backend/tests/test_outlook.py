"""Unit tests for OutlookSource — all HTTP calls and DB writes are mocked or isolated."""
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required env vars before any project imports
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)  # 32 bytes in hex
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost:8000/auth/outlook/callback")

from services.sources.outlook import OutlookSource


def _apply_schema(db_path: str) -> None:
    schema = pathlib.Path(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
    ).read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()


def _make_httpx_mock(post_payload: dict | None = None, get_payload: dict | None = None) -> MagicMock:
    """Build an AsyncMock httpx.AsyncClient with configurable post/get responses."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    if post_payload is not None:
        post_resp = MagicMock()
        post_resp.json.return_value = post_payload
        post_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=post_resp)

    if get_payload is not None:
        get_resp = MagicMock()
        get_resp.json.return_value = get_payload
        get_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=get_resp)

    return mock_client


class TestGetAuthUrl(unittest.IsolatedAsyncioTestCase):
    async def test_returns_microsoft_authorize_url(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("login.microsoftonline.com", url)
        self.assertIn("authorize", url)

    async def test_contains_client_id(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("test-client-id", url)

    async def test_contains_mail_read_scope(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("Mail.Read", url)

    async def test_contains_offline_access_scope(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("offline_access", url)

    async def test_contains_response_type_code(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("response_type=code", url)

    async def test_state_contains_user_id(self) -> None:
        url = await OutlookSource().get_auth_url("unique-user-xyz")
        self.assertIn("unique-user-xyz", url)

    async def test_redirect_uri_included(self) -> None:
        url = await OutlookSource().get_auth_url("user-1")
        self.assertIn("redirect_uri", url)


class TestHandleCallback(unittest.IsolatedAsyncioTestCase):
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

    async def _insert_user(self, user_id: str) -> None:
        import db
        await db.upsert_user(user_id, f"{user_id}@test.com", "2026-01-01T00:00:00Z")

    async def test_stores_token_row(self) -> None:
        await self._insert_user("u-cb-store")

        mock = _make_httpx_mock(
            post_payload={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
            get_payload={"mail": "user@outlook.com"},
        )
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            await OutlookSource().handle_callback("u-cb-store", "code-abc")

        import db
        row = await db.get_source_token("u-cb-store", "outlook")
        self.assertIsNotNone(row)
        self.assertEqual(row["provider_email"], "user@outlook.com")

    async def test_tokens_are_stored_encrypted(self) -> None:
        await self._insert_user("u-cb-enc")

        mock = _make_httpx_mock(
            post_payload={"access_token": "plaintext-at", "refresh_token": "plaintext-rt", "expires_in": 3600},
            get_payload={"mail": "enc@outlook.com"},
        )
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            await OutlookSource().handle_callback("u-cb-enc", "code")

        import db
        row = await db.get_source_token("u-cb-enc", "outlook")
        self.assertNotEqual(row["access_token_enc"], "plaintext-at")
        self.assertNotEqual(row["refresh_token_enc"], "plaintext-rt")

    async def test_falls_back_to_user_principal_name(self) -> None:
        await self._insert_user("u-cb-upn")

        mock = _make_httpx_mock(
            post_payload={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
            get_payload={"mail": None, "userPrincipalName": "user@tenant.onmicrosoft.com"},
        )
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            await OutlookSource().handle_callback("u-cb-upn", "code")

        import db
        row = await db.get_source_token("u-cb-upn", "outlook")
        self.assertEqual(row["provider_email"], "user@tenant.onmicrosoft.com")

    async def test_raises_runtime_error_on_http_failure(self) -> None:
        import httpx
        mock = MagicMock()
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        mock.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            with self.assertRaises(RuntimeError):
                await OutlookSource().handle_callback("u-cb-fail", "code")

    async def test_second_callback_overwrites_existing_token(self) -> None:
        await self._insert_user("u-cb-overwrite")

        mock1 = _make_httpx_mock(
            post_payload={"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600},
            get_payload={"mail": "first@outlook.com"},
        )
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock1):
            await OutlookSource().handle_callback("u-cb-overwrite", "code1")

        mock2 = _make_httpx_mock(
            post_payload={"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600},
            get_payload={"mail": "second@outlook.com"},
        )
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock2):
            await OutlookSource().handle_callback("u-cb-overwrite", "code2")

        import db
        row = await db.get_source_token("u-cb-overwrite", "outlook")
        self.assertEqual(row["provider_email"], "second@outlook.com")


class TestFetchEmails(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_token(self, user_id: str, expires_at: str) -> None:
        import db
        from services.token_store import encrypt
        await db.upsert_user(user_id, f"{user_id}@test.com", "2026-01-01T00:00:00Z")
        await db.upsert_source_token(
            token_id=f"tok-{user_id}",
            user_id=user_id,
            provider="outlook",
            provider_email="test@outlook.com",
            access_token_enc=encrypt("valid-access-token"),
            refresh_token_enc=encrypt("valid-refresh-token"),
            expires_at=expires_at,
            created_at="2026-01-01T00:00:00Z",
        )

    def _future_expires(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def _past_expires(self) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    async def test_maps_graph_response_fields(self) -> None:
        await self._seed_token("u-fetch-map", self._future_expires())

        mock = _make_httpx_mock(get_payload={
            "value": [{
                "id": "msg-1",
                "subject": "Test Subject",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                "bodyPreview": "Hello there",
                "receivedDateTime": "2026-01-01T10:00:00Z",
                "isRead": False,
                "conversationId": "conv-1",
                "hasAttachments": True,
            }]
        })
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            emails = await OutlookSource().fetch_emails("u-fetch-map", since=None)

        self.assertEqual(len(emails), 1)
        msg = emails[0]
        self.assertEqual(msg.id, "msg-1")
        self.assertEqual(msg.subject, "Test Subject")
        self.assertEqual(msg.sender_name, "Alice")
        self.assertEqual(msg.sender_email, "alice@example.com")
        self.assertEqual(msg.body_preview, "Hello there")
        self.assertFalse(msg.is_read)
        self.assertEqual(msg.conversation_id, "conv-1")
        self.assertTrue(msg.has_attachments)

    async def test_since_none_defaults_to_24h_filter(self) -> None:
        await self._seed_token("u-fetch-since", self._future_expires())

        mock = _make_httpx_mock(get_payload={"value": []})
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            await OutlookSource().fetch_emails("u-fetch-since", since=None)

        call_kwargs = mock.get.call_args.kwargs
        filter_param = call_kwargs["params"]["$filter"]
        self.assertIn("receivedDateTime ge", filter_param)

    async def test_returns_empty_list_when_no_emails(self) -> None:
        await self._seed_token("u-fetch-empty", self._future_expires())

        mock = _make_httpx_mock(get_payload={"value": []})
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            emails = await OutlookSource().fetch_emails("u-fetch-empty", since=datetime.now(timezone.utc))

        self.assertEqual(emails, [])

    async def test_returns_multiple_emails(self) -> None:
        await self._seed_token("u-fetch-multi", self._future_expires())

        items = [
            {
                "id": f"msg-{i}",
                "subject": f"Subject {i}",
                "from": {"emailAddress": {"name": "Sender", "address": "s@example.com"}},
                "bodyPreview": "preview",
                "receivedDateTime": "2026-01-01T10:00:00Z",
                "isRead": True,
                "conversationId": None,
                "hasAttachments": False,
            }
            for i in range(5)
        ]
        mock = _make_httpx_mock(get_payload={"value": items})
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            emails = await OutlookSource().fetch_emails("u-fetch-multi", since=None)

        self.assertEqual(len(emails), 5)

    async def test_raises_runtime_error_on_no_token(self) -> None:
        with self.assertRaises(RuntimeError):
            await OutlookSource().fetch_emails("u-no-token-at-all", since=None)

    async def test_raises_runtime_error_on_graph_http_failure(self) -> None:
        import httpx
        await self._seed_token("u-fetch-fail", self._future_expires())

        mock = MagicMock()
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        mock.get = AsyncMock(side_effect=httpx.ConnectError("network down"))

        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            with self.assertRaises(RuntimeError):
                await OutlookSource().fetch_emails("u-fetch-fail", since=None)

    async def test_null_subject_replaced_with_no_subject_placeholder(self) -> None:
        await self._seed_token("u-fetch-null-subj", self._future_expires())

        mock = _make_httpx_mock(get_payload={"value": [{
            "id": "msg-null",
            "subject": None,
            "from": {"emailAddress": {"name": "Sender", "address": "s@example.com"}},
            "bodyPreview": "",
            "receivedDateTime": "2026-01-01T10:00:00Z",
            "isRead": False,
            "conversationId": None,
            "hasAttachments": False,
        }]})
        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            emails = await OutlookSource().fetch_emails("u-fetch-null-subj", since=None)

        self.assertEqual(emails[0].subject, "(no subject)")


class TestTokenRefresh(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_expired_token(self, user_id: str) -> None:
        import db
        from services.token_store import encrypt
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.upsert_user(user_id, f"{user_id}@test.com", "2026-01-01T00:00:00Z")
        await db.upsert_source_token(
            token_id=f"tok-{user_id}",
            user_id=user_id,
            provider="outlook",
            provider_email="test@outlook.com",
            access_token_enc=encrypt("old-access"),
            refresh_token_enc=encrypt("old-refresh"),
            expires_at=past,
            created_at="2026-01-01T00:00:00Z",
        )

    async def test_refresh_is_called_when_token_expired(self) -> None:
        await self._seed_expired_token("u-refresh-expired")

        refresh_mock = MagicMock()
        refresh_mock.__aenter__ = AsyncMock(return_value=refresh_mock)
        refresh_mock.__aexit__ = AsyncMock(return_value=None)
        refresh_resp = MagicMock()
        refresh_resp.json.return_value = {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        }
        refresh_resp.raise_for_status = MagicMock()
        refresh_mock.post = AsyncMock(return_value=refresh_resp)

        graph_mock = MagicMock()
        graph_mock.__aenter__ = AsyncMock(return_value=graph_mock)
        graph_mock.__aexit__ = AsyncMock(return_value=None)
        graph_resp = MagicMock()
        graph_resp.json.return_value = {"value": []}
        graph_resp.raise_for_status = MagicMock()
        graph_mock.get = AsyncMock(return_value=graph_resp)

        call_count = 0

        def client_factory():
            nonlocal call_count
            call_count += 1
            return refresh_mock if call_count == 1 else graph_mock

        with patch("services.sources.outlook.httpx.AsyncClient", side_effect=client_factory):
            await OutlookSource().fetch_emails("u-refresh-expired", since=None)

        refresh_mock.post.assert_called_once()
        data = refresh_mock.post.call_args.kwargs.get("data", {})
        self.assertEqual(data.get("grant_type"), "refresh_token")

    async def test_refresh_updates_stored_token(self) -> None:
        import db
        from services.token_store import decrypt as tok_decrypt
        await self._seed_expired_token("u-refresh-update")

        refresh_mock = MagicMock()
        refresh_mock.__aenter__ = AsyncMock(return_value=refresh_mock)
        refresh_mock.__aexit__ = AsyncMock(return_value=None)
        refresh_resp = MagicMock()
        refresh_resp.json.return_value = {
            "access_token": "fresh-at",
            "refresh_token": "fresh-rt",
            "expires_in": 3600,
        }
        refresh_resp.raise_for_status = MagicMock()
        refresh_mock.post = AsyncMock(return_value=refresh_resp)

        graph_mock = MagicMock()
        graph_mock.__aenter__ = AsyncMock(return_value=graph_mock)
        graph_mock.__aexit__ = AsyncMock(return_value=None)
        graph_resp = MagicMock()
        graph_resp.json.return_value = {"value": []}
        graph_resp.raise_for_status = MagicMock()
        graph_mock.get = AsyncMock(return_value=graph_resp)

        call_count = 0

        def client_factory():
            nonlocal call_count
            call_count += 1
            return refresh_mock if call_count == 1 else graph_mock

        with patch("services.sources.outlook.httpx.AsyncClient", side_effect=client_factory):
            await OutlookSource().fetch_emails("u-refresh-update", since=None)

        row = await db.get_source_token("u-refresh-update", "outlook")
        self.assertEqual(tok_decrypt(row["access_token_enc"]), "fresh-at")
        self.assertEqual(tok_decrypt(row["refresh_token_enc"]), "fresh-rt")

    async def test_refresh_raises_token_refresh_error_on_failure(self) -> None:
        import httpx
        from services.sources.base import TokenRefreshError
        await self._seed_expired_token("u-refresh-fail")

        mock = MagicMock()
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        mock.post = AsyncMock(side_effect=httpx.ConnectError("network down"))

        with patch("services.sources.outlook.httpx.AsyncClient", return_value=mock):
            with self.assertRaises(TokenRefreshError):
                await OutlookSource().fetch_emails("u-refresh-fail", since=None)


class TestRevoke(unittest.IsolatedAsyncioTestCase):
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

    async def test_revoke_deletes_token_row(self) -> None:
        import db
        from services.token_store import encrypt
        await db.upsert_user("u-revoke", "revoke@test.com", "2026-01-01T00:00:00Z")
        await db.upsert_source_token(
            token_id="tok-revoke",
            user_id="u-revoke",
            provider="outlook",
            provider_email="revoke@outlook.com",
            access_token_enc=encrypt("at"),
            refresh_token_enc=encrypt("rt"),
            expires_at="2026-12-31T00:00:00Z",
            created_at="2026-01-01T00:00:00Z",
        )

        await OutlookSource().revoke("u-revoke")

        import db as db2
        row = await db2.get_source_token("u-revoke", "outlook")
        self.assertIsNone(row)

    async def test_revoke_nonexistent_user_is_silent(self) -> None:
        await OutlookSource().revoke("u-nonexistent")


if __name__ == "__main__":
    unittest.main()
