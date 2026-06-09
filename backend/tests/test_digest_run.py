"""Unit tests for POST /digest/run — cron auth, background task, per-user processing."""
import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
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
from routers.digest import _determine_schedule_slot, _process_single_user, _run_digest_for_all_users
from services.sources.base import EmailMessage

_CRON_SECRET = "test-cron-secret-abc123"

_SAMPLE_EMAIL = EmailMessage(
    id="email-1",
    subject="Test Subject",
    sender_name="Sender",
    sender_email="sender@example.com",
    body_preview="Preview text",
    received_at=datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
    is_read=False,
)

_SAMPLE_DIGEST = {
    "digest": {"urgent": [], "action_required": [], "fyi": [], "todos": []},
    "token_usage": {"input_tokens": 100, "output_tokens": 50},
}


class TestRunDigestAuth(unittest.TestCase):
    """POST /digest/run authentication — wrong or missing cron secret must return 403."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_missing_secret_returns_403(self) -> None:
        with patch.dict(os.environ, {"CRON_SECRET": _CRON_SECRET}):
            response = self.client.post("/digest/run")
        self.assertEqual(response.status_code, 403)

    def test_wrong_secret_returns_403(self) -> None:
        with patch.dict(os.environ, {"CRON_SECRET": _CRON_SECRET}):
            response = self.client.post(
                "/digest/run", headers={"X-Cron-Secret": "wrong-secret"}
            )
        self.assertEqual(response.status_code, 403)

    def test_correct_secret_returns_202(self) -> None:
        with (
            patch.dict(os.environ, {"CRON_SECRET": _CRON_SECRET}),
            patch("routers.digest._run_digest_for_all_users", new_callable=AsyncMock),
        ):
            response = self.client.post(
                "/digest/run", headers={"X-Cron-Secret": _CRON_SECRET}
            )
        self.assertEqual(response.status_code, 202)

    def test_correct_secret_returns_accepted_status(self) -> None:
        with (
            patch.dict(os.environ, {"CRON_SECRET": _CRON_SECRET}),
            patch("routers.digest._run_digest_for_all_users", new_callable=AsyncMock),
        ):
            response = self.client.post(
                "/digest/run", headers={"X-Cron-Secret": _CRON_SECRET}
            )
        self.assertEqual(response.json()["status"], "accepted")

    def test_response_includes_schedule_slot(self) -> None:
        with (
            patch.dict(os.environ, {"CRON_SECRET": _CRON_SECRET}),
            patch("routers.digest._run_digest_for_all_users", new_callable=AsyncMock),
        ):
            response = self.client.post(
                "/digest/run", headers={"X-Cron-Secret": _CRON_SECRET}
            )
        self.assertIn(response.json()["schedule_slot"], ("morning", "evening"))


class TestDetermineScheduleSlot(unittest.TestCase):
    """_determine_schedule_slot returns 'morning' before noon, 'evening' after."""

    def test_morning_for_hour_zero(self) -> None:
        mock_now = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        with patch("routers.digest.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            self.assertEqual(_determine_schedule_slot(), "morning")

    def test_morning_for_hour_11(self) -> None:
        mock_now = datetime(2025, 1, 15, 11, 59, 59, tzinfo=timezone.utc)
        with patch("routers.digest.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            self.assertEqual(_determine_schedule_slot(), "morning")

    def test_evening_for_hour_12(self) -> None:
        mock_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        with patch("routers.digest.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            self.assertEqual(_determine_schedule_slot(), "evening")

    def test_evening_for_hour_17(self) -> None:
        mock_now = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
        with patch("routers.digest.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            self.assertEqual(_determine_schedule_slot(), "evening")

    def test_evening_for_hour_23(self) -> None:
        mock_now = datetime(2025, 1, 15, 23, 59, 59, tzinfo=timezone.utc)
        with patch("routers.digest.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            self.assertEqual(_determine_schedule_slot(), "evening")


def _make_settings_row(
    user_id: str = "user-1",
    last_run_at: str | None = None,
    enabled: int = 1,
    schedule: str = "morning",
) -> dict:
    return {
        "user_id": user_id,
        "last_run_at": last_run_at,
        "last_email_id": None,
        "enabled": enabled,
        "schedule": schedule,
        "digest_prefs": "default prefs",
    }


def _make_token_row(user_id: str = "user-1", provider: str = "outlook") -> dict:
    return {"user_id": user_id, "provider": provider}


def _make_dest_row(user_id: str = "user-1", provider: str = "telegram") -> dict:
    return {"user_id": user_id, "provider": provider}


class TestProcessSingleUser(unittest.IsolatedAsyncioTestCase):
    """_process_single_user covers all per-user digest logic paths."""

    async def test_no_settings_returns_silently(self) -> None:
        with patch("routers.digest.db") as mock_db:
            mock_db.get_digest_settings = AsyncMock(return_value=None)
            # Should complete without error and without calling anything else
            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")
            mock_db.update_last_run.assert_not_called()

    async def test_no_source_tokens_returns_silently(self) -> None:
        with patch("routers.digest.db") as mock_db:
            mock_db.get_digest_settings = AsyncMock(
                return_value=_make_settings_row()
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.get_all_source_tokens_for_user = AsyncMock(return_value=[])
            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")
            mock_db.update_last_run.assert_not_called()

    async def test_no_destinations_returns_silently(self) -> None:
        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=[_SAMPLE_EMAIL])
            )}),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(return_value=[])
            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")
            mock_db.update_last_run.assert_not_called()

    async def test_empty_inbox_logs_empty_run_and_updates_last_run(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        inserted_runs: list[dict] = []

        async def fake_insert_run(**kwargs: object) -> None:
            inserted_runs.append(dict(kwargs))

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=[])
            )}),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock(side_effect=fake_insert_run)

            await _process_single_user("user-1", run_at)

        mock_db.update_last_run.assert_called_once_with("user-1", run_at, None)
        self.assertEqual(len(inserted_runs), 1)
        self.assertEqual(inserted_runs[0]["status"], "empty")
        self.assertEqual(inserted_runs[0]["email_count"], 0)

    async def test_last_run_at_null_defaults_to_24h_lookback(self) -> None:
        fetch_calls: list[dict] = []

        async def fake_fetch(user_id: str, since: datetime) -> list:
            fetch_calls.append({"since": since})
            return []

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(side_effect=fake_fetch)
            )}),
        ):
            mock_db.get_digest_settings = AsyncMock(
                return_value=_make_settings_row(last_run_at=None)
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            before = datetime.now(timezone.utc)
            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")
            after = datetime.now(timezone.utc)

        self.assertEqual(len(fetch_calls), 1)
        since_dt: datetime = fetch_calls[0]["since"]
        expected_low = (before - timedelta(hours=24)).timestamp()
        expected_high = (after - timedelta(hours=24)).timestamp()
        self.assertGreaterEqual(since_dt.timestamp(), expected_low - 1)
        self.assertLessEqual(since_dt.timestamp(), expected_high + 1)

    async def test_success_path_sends_digest_and_logs_run(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        inserted_runs: list[dict] = []

        async def fake_insert_run(**kwargs: object) -> None:
            inserted_runs.append(dict(kwargs))

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock()

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=[_SAMPLE_EMAIL])
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
            patch("routers.digest.summarizer.summarize", new_callable=AsyncMock,
                  return_value=_SAMPLE_DIGEST),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock(side_effect=fake_insert_run)

            await _process_single_user("user-1", run_at)

        mock_dest.send_digest.assert_called_once()
        mock_db.update_last_run.assert_called_once_with("user-1", run_at, "email-1")
        self.assertEqual(len(inserted_runs), 1)
        self.assertEqual(inserted_runs[0]["status"], "success")
        self.assertEqual(inserted_runs[0]["email_count"], 1)
        self.assertEqual(inserted_runs[0]["tokens_used"], 150)
        self.assertEqual(inserted_runs[0]["source"], "outlook")
        self.assertEqual(inserted_runs[0]["destination"], "telegram")

    async def test_source_fetch_failure_logs_zero_count_run(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        inserted_runs: list[dict] = []

        async def fake_insert_run(**kwargs: object) -> None:
            inserted_runs.append(dict(kwargs))

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock()

        async def failing_fetch(user_id: str, since: datetime) -> list:
            raise RuntimeError("Graph API error")

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(side_effect=failing_fetch)
            )}),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock(side_effect=fake_insert_run)

            # Should not raise — error is isolated
            await _process_single_user("user-1", run_at)

        # Source failed → treated as 0 emails → empty run logged
        self.assertEqual(len(inserted_runs), 1)
        self.assertEqual(inserted_runs[0]["status"], "empty")
        self.assertEqual(inserted_runs[0]["email_count"], 0)
        mock_db.update_last_run.assert_called_once()

    async def test_summarizer_failure_logs_error_and_skips_update(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        inserted_runs: list[dict] = []

        async def fake_insert_run(**kwargs: object) -> None:
            inserted_runs.append(dict(kwargs))

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=[_SAMPLE_EMAIL])
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": AsyncMock()}),
            patch("routers.digest.summarizer.summarize",
                  new_callable=AsyncMock, side_effect=ValueError("Model error")),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock(side_effect=fake_insert_run)

            await _process_single_user("user-1", run_at)

        self.assertEqual(len(inserted_runs), 1)
        self.assertEqual(inserted_runs[0]["status"], "error")
        self.assertIn("Model error", inserted_runs[0]["error_msg"])
        # last_run_at must NOT be updated on summarizer failure
        mock_db.update_last_run.assert_not_called()

    async def test_destination_failure_logs_error_and_still_updates_last_run(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        inserted_runs: list[dict] = []

        async def fake_insert_run(**kwargs: object) -> None:
            inserted_runs.append(dict(kwargs))

        async def failing_send(user_id: str, digest: dict) -> None:
            raise RuntimeError("Telegram API error")

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock(side_effect=failing_send)

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(return_value=[_SAMPLE_EMAIL])
            )}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
            patch("routers.digest.summarizer.summarize",
                  new_callable=AsyncMock, return_value=_SAMPLE_DIGEST),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock(side_effect=fake_insert_run)

            await _process_single_user("user-1", run_at)

        self.assertEqual(len(inserted_runs), 1)
        self.assertEqual(inserted_runs[0]["status"], "error")
        self.assertIn("Telegram API error", inserted_runs[0]["error_msg"])
        mock_db.update_last_run.assert_called_once_with("user-1", run_at, "email-1")

    async def test_emails_deduplicated_across_sources(self) -> None:
        run_at = "2025-01-15T08:00:00+00:00"
        # Both sources return the same email id
        duplicate = _SAMPLE_EMAIL
        source_a = AsyncMock(fetch_emails=AsyncMock(return_value=[duplicate]))
        source_b = AsyncMock(fetch_emails=AsyncMock(return_value=[duplicate]))

        summarize_calls: list[list] = []

        async def fake_summarize(user_id: str, emails: list, **kwargs: object) -> dict:
            summarize_calls.append(list(emails))
            return _SAMPLE_DIGEST

        mock_dest = AsyncMock()
        mock_dest.send_digest = AsyncMock()

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": source_a, "gmail": source_b}),
            patch("routers.digest.DESTINATION_PROVIDERS", {"telegram": mock_dest}),
            patch("routers.digest.summarizer.summarize", side_effect=fake_summarize),
        ):
            mock_db.get_digest_settings = AsyncMock(return_value=_make_settings_row())
            mock_db.get_all_source_tokens_for_user = AsyncMock(return_value=[
                _make_token_row(provider="outlook"),
                _make_token_row(provider="gmail"),
            ])
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", run_at)

        # Duplicate email id should only appear once in the summarizer call
        self.assertEqual(len(summarize_calls), 1)
        self.assertEqual(len(summarize_calls[0]), 1)

    async def test_last_run_at_string_is_used_as_since(self) -> None:
        """Stored last_run_at ISO string is correctly parsed and passed as 'since'."""
        fetch_calls: list[dict] = []

        async def fake_fetch(user_id: str, since: datetime) -> list:
            fetch_calls.append({"since": since})
            return []

        stored_last_run = "2025-01-14T08:00:00Z"

        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest.SOURCE_PROVIDERS", {"outlook": AsyncMock(
                fetch_emails=AsyncMock(side_effect=fake_fetch)
            )}),
        ):
            mock_db.get_digest_settings = AsyncMock(
                return_value=_make_settings_row(last_run_at=stored_last_run)
            )
            mock_db.get_all_destination_configs_for_user = AsyncMock(
                return_value=[_make_dest_row()]
            )
            mock_db.get_all_source_tokens_for_user = AsyncMock(
                return_value=[_make_token_row()]
            )
            mock_db.update_last_run = AsyncMock()
            mock_db.insert_digest_run = AsyncMock()

            await _process_single_user("user-1", "2025-01-15T08:00:00+00:00")

        self.assertEqual(len(fetch_calls), 1)
        since_dt: datetime = fetch_calls[0]["since"]
        expected = datetime(2025, 1, 14, 8, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(since_dt, expected)


class TestRunDigestForAllUsers(unittest.IsolatedAsyncioTestCase):
    """_run_digest_for_all_users processes each enabled user independently."""

    async def test_processes_all_enabled_users(self) -> None:
        processed: list[str] = []

        async def fake_process(user_id: str, run_at: str) -> None:
            processed.append(user_id)

        rows = [{"user_id": "user-A"}, {"user_id": "user-B"}]
        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest._process_single_user", side_effect=fake_process),
        ):
            mock_db.delete_expired_telegram_link_codes = AsyncMock()
            mock_db.get_enabled_users_for_schedule = AsyncMock(return_value=rows)
            await _run_digest_for_all_users("morning")

        self.assertIn("user-A", processed)
        self.assertIn("user-B", processed)

    async def test_one_user_error_does_not_affect_others(self) -> None:
        processed: list[str] = []

        async def fake_process(user_id: str, run_at: str) -> None:
            if user_id == "user-A":
                raise RuntimeError("Something went wrong")
            processed.append(user_id)

        rows = [{"user_id": "user-A"}, {"user_id": "user-B"}]
        with (
            patch("routers.digest.db") as mock_db,
            patch("routers.digest._process_single_user", side_effect=fake_process),
        ):
            mock_db.delete_expired_telegram_link_codes = AsyncMock()
            mock_db.get_enabled_users_for_schedule = AsyncMock(return_value=rows)
            # Should not raise even though user-A fails
            await _run_digest_for_all_users("morning")

        self.assertIn("user-B", processed)
        self.assertNotIn("user-A", processed)

    async def test_queries_correct_schedule_slot(self) -> None:
        with patch("routers.digest.db") as mock_db:
            mock_db.delete_expired_telegram_link_codes = AsyncMock()
            mock_db.get_enabled_users_for_schedule = AsyncMock(return_value=[])
            await _run_digest_for_all_users("evening")
            mock_db.get_enabled_users_for_schedule.assert_called_once_with("evening")

    async def test_no_users_completes_without_error(self) -> None:
        with patch("routers.digest.db") as mock_db:
            mock_db.delete_expired_telegram_link_codes = AsyncMock()
            mock_db.get_enabled_users_for_schedule = AsyncMock(return_value=[])
            # Should not raise
            await _run_digest_for_all_users("morning")


if __name__ == "__main__":
    unittest.main()
