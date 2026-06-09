"""Unit tests for Phase 8: hardening, error resilience, safety caps, and observability."""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("NEXTAUTH_SECRET", "test-nextauth-secret")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost/callback")

from starlette.testclient import TestClient

from main import app
from routers.digest import _EMAIL_CAP, _process_single_user, _run_digest_for_all_users, _send_reconnect_notice
from services.sources.base import EmailMessage, TokenRefreshError
from services.summarizer import build_prompt, _TRUNCATION_NOTE

_ADMIN_SECRET = "test-admin-secret-xyz"

_SAMPLE_EMAIL = EmailMessage(
    id="email-1",
    subject="Test",
    sender_name="Sender",
    sender_email="s@example.com",
    body_preview="Preview",
    received_at=datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
    is_read=False,
)

_SAMPLE_DIGEST = {
    "digest": {"urgent": [], "action_required": [], "fyi": [], "todos": []},
    "token_usage": {"input_tokens": 100, "output_tokens": 50},
}


def _make_settings_row(
    user_id: str = "user-1",
    last_run_at: str | None = None,
) -> dict:
    return {
        "user_id": user_id,
        "last_run_at": last_run_at,
        "last_email_id": None,
        "enabled": 1,
        "schedule": "morning",
        "digest_prefs": "default prefs",
    }


def _make_token_row(provider: str = "outlook") -> dict:
    return {"user_id": "user-1", "provider": provider}


def _make_dest_row(provider: str = "telegram") -> dict:
    return {"user_id": "user-1", "provider": provider}


# ---------------------------------------------------------------------------
# Admin stats endpoint
# ---------------------------------------------------------------------------

class TestAdminStatsEndpoint(unittest.TestCase):
    """GET /admin/stats — protected by X-Admin-Secret header."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_missing_secret_returns_403(self) -> None:
        with patch.dict(os.environ, {"ADMIN_SECRET": _ADMIN_SECRET}):
            resp = self.client.get("/admin/stats")
        self.assertEqual(resp.status_code, 403)

    def test_wrong_secret_returns_403(self) -> None:
        with patch.dict(os.environ, {"ADMIN_SECRET": _ADMIN_SECRET}):
            resp = self.client.get("/admin/stats", headers={"X-Admin-Secret": "wrong"})
        self.assertEqual(resp.status_code, 403)

    def test_cron_secret_does_not_work_for_admin(self) -> None:
        """Cron secret must not bypass the admin endpoint."""
        with patch.dict(os.environ, {"ADMIN_SECRET": _ADMIN_SECRET, "CRON_SECRET": "cron-abc"}):
            resp = self.client.get("/admin/stats", headers={"X-Admin-Secret": "cron-abc"})
        self.assertEqual(resp.status_code, 403)

    def test_correct_secret_returns_200_with_stats(self) -> None:
        mock_stats = {
            "user_count": 2,
            "total_runs": 10,
            "success_runs": 8,
            "error_runs": 2,
            "error_rate": 0.2,
            "per_user": [],
        }
        with (
            patch.dict(os.environ, {"ADMIN_SECRET": _ADMIN_SECRET}),
            patch("routers.admin.db.get_admin_stats", new_callable=AsyncMock, return_value=mock_stats),
        ):
            resp = self.client.get("/admin/stats", headers={"X-Admin-Secret": _ADMIN_SECRET})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["user_count"], 2)
        self.assertEqual(body["total_runs"], 10)
        self.assertIn("error_rate", body)
        self.assertIn("per_user", body)

    def test_stats_response_includes_all_required_fields(self) -> None:
        mock_stats = {
            "user_count": 0,
            "total_runs": 0,
            "success_runs": 0,
            "error_runs": 0,
            "error_rate": 0.0,
            "per_user": [],
        }
        with (
            patch.dict(os.environ, {"ADMIN_SECRET": _ADMIN_SECRET}),
            patch("routers.admin.db.get_admin_stats", new_callable=AsyncMock, return_value=mock_stats),
        ):
            resp = self.client.get("/admin/stats", headers={"X-Admin-Secret": _ADMIN_SECRET})
        for field in ("user_count", "total_runs", "success_runs", "error_runs", "error_rate", "per_user"):
            self.assertIn(field, resp.json())


# ---------------------------------------------------------------------------
# TokenRefreshError → reconnect notice
# ---------------------------------------------------------------------------

class TestTokenRefreshErrorHandling(unittest.IsolatedAsyncioTestCase):
    """When a source token refresh fails, a reconnect notice is sent to all destinations."""

    async def test_token_refresh_error_triggers_reconnect_notice(self) -> None:
        notified: list[dict] = []

        async def fake_notify(user_id: str, provider: str, dest_configs: list) -> None:
            notified.append({"user_id": user_id, "provider": provider})

        dest_configs = [_make_dest_row()]

        async def failing_fetch(user_id: str, since: datetime) -> list:
            raise TokenRefreshError("refresh_token revoked")

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(side_effect=failing_fetch)
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": AsyncMock()}),
            patch("routers.digest._send_reconnect_notice", side_effect=fake_notify),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_destination_configs_for_user = AsyncMock(return_value=dest_configs)
            mock_db.get_all_source_tokens_for_user = AsyncMock(return_value=[_make_token_row()])
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")

        self.assertEqual(len(notified), 1)
        self.assertEqual(notified[0]["provider"], "outlook")
        self.assertEqual(notified[0]["user_id"], "user-1")

    async def test_generic_source_error_does_not_trigger_reconnect_notice(self) -> None:
        notified: list[dict] = []

        async def fake_notify(user_id: str, provider: str, dest_configs: list) -> None:
            notified.append({"user_id": user_id, "provider": provider})

        async def failing_fetch(user_id: str, since: datetime) -> list:
            raise RuntimeError("network error")

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(side_effect=failing_fetch)
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": AsyncMock()}),
            patch("routers.digest._send_reconnect_notice", side_effect=fake_notify),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_destination_configs_for_user = AsyncMock(return_value=[_make_dest_row()])
            mock_db.get_all_source_tokens_for_user = AsyncMock(return_value=[_make_token_row()])
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")

        self.assertEqual(len(notified), 0)

    async def test_send_reconnect_notice_calls_send_notification_on_each_dest(self) -> None:
        mock_dest = AsyncMock()
        mock_dest.send_notification = AsyncMock()

        dest_configs = [_make_dest_row("telegram")]

        with (
            patch.dict(os.environ, {"FRONTEND_URL": "https://app.example.com"}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
        ):
            await _send_reconnect_notice("user-1", "outlook", dest_configs)

        mock_dest.send_notification.assert_called_once()
        call_args = mock_dest.send_notification.call_args
        self.assertEqual(call_args[0][0], "user-1")
        self.assertIn("Outlook", call_args[0][1])
        self.assertIn("https://app.example.com/settings", call_args[0][1])

    async def test_send_reconnect_notice_skips_unknown_provider(self) -> None:
        mock_dest = AsyncMock()
        mock_dest.send_notification = AsyncMock()

        dest_configs = [_make_dest_row("teams")]  # not in registry

        with patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}):
            await _send_reconnect_notice("user-1", "outlook", dest_configs)

        mock_dest.send_notification.assert_not_called()

    async def test_send_reconnect_notice_survives_notification_failure(self) -> None:
        """A failed notification must not raise — the error is logged and swallowed."""
        mock_dest = AsyncMock()
        mock_dest.send_notification = AsyncMock(side_effect=RuntimeError("send failed"))

        dest_configs = [_make_dest_row("telegram")]

        with patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}):
            # Must not raise
            await _send_reconnect_notice("user-1", "outlook", dest_configs)


# ---------------------------------------------------------------------------
# 100-email safety cap
# ---------------------------------------------------------------------------

class TestEmailCap(unittest.IsolatedAsyncioTestCase):
    """Merged email list is capped at 100 before summarization."""

    def _make_emails(self, count: int) -> list[EmailMessage]:
        return [
            EmailMessage(
                id=f"email-{i}",
                subject=f"Subject {i}",
                sender_name="Sender",
                sender_email="s@example.com",
                body_preview="Preview",
                received_at=datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
                is_read=False,
            )
            for i in range(count)
        ]

    async def test_101_emails_truncated_to_100(self) -> None:
        emails = self._make_emails(101)
        summarize_calls: list[dict] = []

        async def fake_summarize(user_id: str, email_list: list, **kwargs: object) -> dict:
            summarize_calls.append({"count": len(email_list), "truncated": kwargs.get("truncated")})
            return _SAMPLE_DIGEST

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock()

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=emails)
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
            patch("routers.digest.summarizer.summarize", side_effect=fake_summarize),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")

        self.assertEqual(len(summarize_calls), 1)
        self.assertEqual(summarize_calls[0]["count"], 100)
        self.assertTrue(summarize_calls[0]["truncated"])

    async def test_exactly_100_emails_not_truncated(self) -> None:
        emails = self._make_emails(100)
        summarize_calls: list[dict] = []

        async def fake_summarize(user_id: str, email_list: list, **kwargs: object) -> dict:
            summarize_calls.append({"count": len(email_list), "truncated": kwargs.get("truncated")})
            return _SAMPLE_DIGEST

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock()

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=emails)
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
            patch("routers.digest.summarizer.summarize", side_effect=fake_summarize),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")

        self.assertEqual(len(summarize_calls), 1)
        self.assertEqual(summarize_calls[0]["count"], 100)
        self.assertFalse(summarize_calls[0]["truncated"])

    async def test_email_cap_constant_is_100(self) -> None:
        self.assertEqual(_EMAIL_CAP, 100)


# ---------------------------------------------------------------------------
# build_prompt truncation note
# ---------------------------------------------------------------------------

class TestBuildPromptTruncation(unittest.TestCase):
    """build_prompt appends a truncation note when truncated=True."""

    def _sample_emails(self) -> list[EmailMessage]:
        return [_SAMPLE_EMAIL]

    def test_truncation_note_absent_by_default(self) -> None:
        prompt = build_prompt("user@example.com", "my prefs", self._sample_emails())
        self.assertNotIn("100 most recent", prompt)

    def test_truncation_note_present_when_truncated(self) -> None:
        prompt = build_prompt(
            "user@example.com", "my prefs", self._sample_emails(), truncated=True
        )
        self.assertIn(_TRUNCATION_NOTE, prompt)

    def test_truncation_note_not_present_when_false(self) -> None:
        prompt = build_prompt(
            "user@example.com", "my prefs", self._sample_emails(), truncated=False
        )
        self.assertNotIn(_TRUNCATION_NOTE, prompt)


# ---------------------------------------------------------------------------
# Expired Telegram link code cleanup
# ---------------------------------------------------------------------------

class TestExpiredLinkCodeCleanup(unittest.IsolatedAsyncioTestCase):
    """delete_expired_telegram_link_codes is called on every digest/run trigger."""

    async def test_cleanup_called_on_run(self) -> None:
        cleanup_calls: list[str] = []

        async def fake_cleanup(now: str) -> None:
            cleanup_calls.append(now)

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest._process_single_user", new_callable=AsyncMock),
        ):
            mock_db.delete_expired_telegram_link_codes = AsyncMock(side_effect=fake_cleanup)
            mock_db.get_enabled_users_for_schedule = AsyncMock(return_value=[])
            await _run_digest_for_all_users("morning")

        self.assertEqual(len(cleanup_calls), 1)

    async def test_cleanup_called_before_user_processing(self) -> None:
        call_order: list[str] = []

        async def fake_cleanup(now: str) -> None:
            call_order.append("cleanup")

        async def fake_process(user_id: str, run_at: str) -> None:
            call_order.append(f"process:{user_id}")

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest._process_single_user", side_effect=fake_process),
        ):
            mock_db.delete_expired_telegram_link_codes = AsyncMock(side_effect=fake_cleanup)
            mock_db.get_enabled_users_for_schedule = AsyncMock(
                return_value=[{"user_id": "user-1"}]
            )
            await _run_digest_for_all_users("morning")

        self.assertEqual(call_order[0], "cleanup")
        self.assertEqual(call_order[1], "process:user-1")


# ---------------------------------------------------------------------------
# Summarizer retry backoff
# ---------------------------------------------------------------------------

class TestSummarizerRetryBackoff(unittest.IsolatedAsyncioTestCase):
    """Claude API retry waits 2 seconds between attempts."""

    async def test_sleep_called_between_retries(self) -> None:
        import json
        from services.summarizer import _call_with_retry

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        mock_message = MagicMock()
        mock_message.usage.input_tokens = 100
        mock_message.usage.output_tokens = 50
        # First attempt returns malformed JSON; second returns valid JSON
        valid_json = json.dumps({"urgent": [], "action_required": [], "fyi": [], "todos": []})
        mock_message.content = [MagicMock(text=valid_json)]

        call_count = 0

        async def fake_create(**kwargs: object) -> MagicMock:
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                bad = MagicMock()
                bad.usage.input_tokens = 100
                bad.usage.output_tokens = 50
                bad.content = [MagicMock(text="not json {{{")]
                return bad
            return mock_message

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=fake_create)

        with patch("services.summarizer.asyncio.sleep", side_effect=fake_sleep):
            await _call_with_retry(mock_client, "test prompt")

        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(sleep_calls[0], 2)

    async def test_no_sleep_on_first_success(self) -> None:
        import json
        from services.summarizer import _call_with_retry

        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        valid_json = json.dumps({"urgent": [], "action_required": [], "fyi": [], "todos": []})
        mock_message = MagicMock()
        mock_message.usage.input_tokens = 50
        mock_message.usage.output_tokens = 30
        mock_message.content = [MagicMock(text=valid_json)]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("services.summarizer.asyncio.sleep", side_effect=fake_sleep):
            await _call_with_retry(mock_client, "test prompt")

        self.assertEqual(len(sleep_calls), 0)


# ---------------------------------------------------------------------------
# TelegramDestination.send_notification
# ---------------------------------------------------------------------------

class TestTelegramSendNotification(unittest.IsolatedAsyncioTestCase):
    """TelegramDestination.send_notification sends plain text via send_telegram_message."""

    async def test_send_notification_calls_send_telegram_message(self) -> None:
        from services.destinations.telegram import TelegramDestination

        dest = TelegramDestination()
        message_calls: list[dict] = []

        async def fake_load_config(user_id: str) -> dict:
            return {"chat_id": 42}

        async def fake_send(chat_id: int, text: str) -> None:
            message_calls.append({"chat_id": chat_id, "text": text})

        with (
            patch.object(dest, "_load_config", side_effect=fake_load_config),
            patch("services.destinations.telegram.send_telegram_message", side_effect=fake_send),
        ):
            await dest.send_notification("user-1", "Hello from the bot!")

        self.assertEqual(len(message_calls), 1)
        self.assertEqual(message_calls[0]["chat_id"], 42)
        self.assertEqual(message_calls[0]["text"], "Hello from the bot!")

    async def test_send_notification_default_noop_on_base_class(self) -> None:
        """The base class default send_notification must not raise."""
        from services.destinations.base import DigestDestination

        class MinimalDest(DigestDestination):
            async def connect(self, user_id: str, config: dict) -> None:
                pass

            async def send_digest(self, user_id: str, digest: dict) -> None:
                pass

            async def disconnect(self, user_id: str) -> None:
                pass

        dest = MinimalDest()
        # Must not raise
        await dest.send_notification("user-1", "test message")


# ---------------------------------------------------------------------------
# TokenRefreshError defined in sources/base
# ---------------------------------------------------------------------------

class TestTokenRefreshError(unittest.TestCase):
    """TokenRefreshError is a distinct exception type."""

    def test_is_exception_subclass(self) -> None:
        self.assertTrue(issubclass(TokenRefreshError, Exception))

    def test_can_be_raised_and_caught(self) -> None:
        with self.assertRaises(TokenRefreshError):
            raise TokenRefreshError("token revoked")

    def test_not_caught_by_value_error(self) -> None:
        self.assertFalse(issubclass(TokenRefreshError, ValueError))

    def test_not_same_as_runtime_error(self) -> None:
        self.assertFalse(issubclass(TokenRefreshError, RuntimeError))


# ---------------------------------------------------------------------------
# OutlookSource raises TokenRefreshError on refresh failure
# ---------------------------------------------------------------------------

class TestOutlookTokenRefreshError(unittest.IsolatedAsyncioTestCase):
    """OutlookSource._refresh_token raises TokenRefreshError on HTTP failure."""

    async def test_refresh_failure_raises_token_refresh_error(self) -> None:
        import httpx
        from services.sources.outlook import OutlookSource

        source = OutlookSource()

        async def fake_post(*args: object, **kwargs: object) -> MagicMock:
            raise httpx.HTTPError("401 Unauthorized")

        with patch("services.sources.outlook.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("token expired"))
            mock_client_cls.return_value = mock_client

            with self.assertRaises(TokenRefreshError):
                await source._refresh_token("user-1", "old-refresh-token")


if __name__ == "__main__":
    unittest.main()
