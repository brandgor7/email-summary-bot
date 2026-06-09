"""Unit tests for /digest/preview — rate limiting, 404 for unknown source, success path."""
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_SECRET = "test-nextauth-secret"
os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost/callback")

import jwt
from starlette.testclient import TestClient

from main import app


def _valid_token(sub: str = "user-preview") -> str:
    return jwt.encode(
        {"sub": sub, "exp": int(time.time()) + 3600},
        _TEST_SECRET,
        algorithm="HS256",
    )


_EMPTY_DIGEST = {
    "digest": {"urgent": [], "action_required": [], "fyi": [], "todos": []},
    "token_usage": {"input_tokens": 10, "output_tokens": 20},
}


class TestPreviewUnknownSource(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_valid_token()}"}

    def test_unknown_source_returns_404(self) -> None:
        response = self.client.post(
            "/digest/preview",
            json={"source": "not_a_real_provider"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_source_error_message(self) -> None:
        response = self.client.post(
            "/digest/preview",
            json={"source": "gmail"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("gmail", response.json()["detail"])


class TestPreviewRateLimit(unittest.TestCase):
    """11th call within an hour must return 429 with Retry-After header."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_eleventh_call_returns_429(self) -> None:
        import routers.digest as digest_module

        unique_user = "rate-limit-test-user"
        token = _valid_token(sub=unique_user)
        headers = {"Authorization": f"Bearer {token}"}

        # Pre-populate 10 timestamps in the current window so the next call is #11
        now = datetime.now(timezone.utc).timestamp()
        digest_module._preview_timestamps[unique_user] = [now - i for i in range(10)]

        with patch("routers.digest.summarizer.summarize", new_callable=AsyncMock):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=headers,
            )

        self.assertEqual(response.status_code, 429)

    def test_429_response_has_retry_after_header(self) -> None:
        import routers.digest as digest_module

        unique_user = "rate-limit-header-user"
        token = _valid_token(sub=unique_user)
        headers = {"Authorization": f"Bearer {token}"}

        now = datetime.now(timezone.utc).timestamp()
        digest_module._preview_timestamps[unique_user] = [now - i for i in range(10)]

        with patch("routers.digest.summarizer.summarize", new_callable=AsyncMock):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=headers,
            )

        self.assertIn("retry-after", response.headers)
        retry_after = int(response.headers["retry-after"])
        self.assertGreater(retry_after, 0)

    def test_calls_within_limit_are_allowed(self) -> None:
        import routers.digest as digest_module

        unique_user = "rate-limit-allowed-user"
        token = _valid_token(sub=unique_user)
        headers = {"Authorization": f"Bearer {token}"}

        # Clear any existing timestamps for this user
        digest_module._preview_timestamps[unique_user] = []

        mock_emails: list = []
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=mock_emails))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=headers,
            )

        self.assertNotEqual(response.status_code, 429)

    def test_expired_timestamps_are_not_counted(self) -> None:
        import routers.digest as digest_module

        unique_user = "rate-limit-expired-user"
        token = _valid_token(sub=unique_user)
        headers = {"Authorization": f"Bearer {token}"}

        # Set 10 timestamps that are all outside the 1-hour window
        old_time = datetime.now(timezone.utc).timestamp() - 7200  # 2 hours ago
        digest_module._preview_timestamps[unique_user] = [old_time] * 10

        mock_emails: list = []
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=mock_emails))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=headers,
            )

        # Expired timestamps should not block the request
        self.assertNotEqual(response.status_code, 429)


class TestPreviewSuccess(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.unique_user = "preview-success-user"
        cls.headers = {"Authorization": f"Bearer {_valid_token(sub=cls.unique_user)}"}

    def setUp(self) -> None:
        import routers.digest as digest_module
        digest_module._preview_timestamps[self.unique_user] = []

    def test_returns_digest_and_token_usage(self) -> None:
        digest = {
            "urgent": [{"subject": "Urgent", "sender": "boss", "summary": "s", "reason": "r", "suggested_action": "a"}],
            "action_required": [],
            "fyi": [],
            "todos": [],
        }
        mock_result = {"digest": digest, "token_usage": {"input_tokens": 100, "output_tokens": 200}}

        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("digest", body)
        self.assertIn("token_usage", body)
        self.assertEqual(body["digest"]["urgent"][0]["subject"], "Urgent")

    def test_digest_prefs_override_is_passed_to_summarize(self) -> None:
        captured_kwargs: list[dict] = []

        async def fake_summarize(user_id, emails, digest_prefs_override=None):
            captured_kwargs.append({"digest_prefs_override": digest_prefs_override})
            return _EMPTY_DIGEST

        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch("routers.digest.summarizer.summarize", side_effect=fake_summarize),
        ):
            self.client.post(
                "/digest/preview",
                json={"source": "outlook", "digest_prefs_override": "Custom prefs"},
                headers=self.headers,
            )

        self.assertEqual(captured_kwargs[0]["digest_prefs_override"], "Custom prefs")

    def test_no_digest_prefs_override_passes_none(self) -> None:
        captured_kwargs: list[dict] = []

        async def fake_summarize(user_id, emails, digest_prefs_override=None):
            captured_kwargs.append({"digest_prefs_override": digest_prefs_override})
            return _EMPTY_DIGEST

        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch("routers.digest.summarizer.summarize", side_effect=fake_summarize),
        ):
            self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=self.headers,
            )

        self.assertIsNone(captured_kwargs[0]["digest_prefs_override"])

    def test_since_hours_controls_fetch_window(self) -> None:
        fetch_calls: list[dict] = []

        async def fake_fetch(user_id, since):
            fetch_calls.append({"since": since})
            return []

        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(side_effect=fake_fetch))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            before = datetime.now(timezone.utc)
            self.client.post(
                "/digest/preview",
                json={"source": "outlook", "since_hours": 48},
                headers=self.headers,
            )
            after = datetime.now(timezone.utc)

        self.assertEqual(len(fetch_calls), 1)
        since_dt: datetime = fetch_calls[0]["since"]
        # since should be roughly 48 hours before now
        expected_low = before.timestamp() - 48 * 3600 - 5
        expected_high = after.timestamp() - 48 * 3600 + 5
        self.assertGreaterEqual(since_dt.timestamp(), expected_low)
        self.assertLessEqual(since_dt.timestamp(), expected_high)

    def test_requires_authentication(self) -> None:
        response = self.client.post("/digest/preview", json={"source": "outlook"})
        self.assertEqual(response.status_code, 401)


class TestPreviewSendTo(unittest.TestCase):
    """Tests for the optional send_to field on /digest/preview."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.unique_user = "preview-send-to-user"
        cls.headers = {"Authorization": f"Bearer {_valid_token(sub=cls.unique_user)}"}

    def setUp(self) -> None:
        import routers.digest as digest_module
        digest_module._preview_timestamps[self.unique_user] = []

    def test_send_to_unknown_destination_returns_404(self) -> None:
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook", "send_to": "carrier_pigeon"},
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 404)
        self.assertIn("carrier_pigeon", response.json()["detail"])

    def test_send_to_calls_destination_send_digest(self) -> None:
        mock_send_digest = AsyncMock()
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
            patch(
                "routers.digest.DESTINATION_PROVIDERS",
                {"telegram": AsyncMock(send_digest=mock_send_digest)},
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook", "send_to": "telegram"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        mock_send_digest.assert_called_once()

    def test_send_to_success_includes_send_result(self) -> None:
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
            patch(
                "routers.digest.DESTINATION_PROVIDERS",
                {"telegram": AsyncMock(send_digest=AsyncMock())},
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook", "send_to": "telegram"},
                headers=self.headers,
            )

        body = response.json()
        self.assertEqual(body["send_result"]["status"], "sent")
        self.assertEqual(body["send_result"]["destination"], "telegram")

    def test_send_to_failure_returns_digest_with_error_status(self) -> None:
        mock_send = AsyncMock(side_effect=RuntimeError("Telegram unavailable"))
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
            patch(
                "routers.digest.DESTINATION_PROVIDERS",
                {"telegram": AsyncMock(send_digest=mock_send)},
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook", "send_to": "telegram"},
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("digest", body)
        self.assertEqual(body["send_result"]["status"], "error")
        self.assertIn("Telegram unavailable", body["send_result"]["error"])

    def test_no_send_to_returns_no_send_result(self) -> None:
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook"},
                headers=self.headers,
            )

        body = response.json()
        self.assertNotIn("send_result", body)

    def test_send_to_none_returns_no_send_result(self) -> None:
        with (
            patch(
                "routers.digest.SOURCE_PROVIDERS",
                {"outlook": AsyncMock(fetch_emails=AsyncMock(return_value=[]))},
            ),
            patch(
                "routers.digest.summarizer.summarize",
                new_callable=AsyncMock,
                return_value=_EMPTY_DIGEST,
            ),
        ):
            response = self.client.post(
                "/digest/preview",
                json={"source": "outlook", "send_to": None},
                headers=self.headers,
            )

        body = response.json()
        self.assertNotIn("send_result", body)


if __name__ == "__main__":
    unittest.main()
