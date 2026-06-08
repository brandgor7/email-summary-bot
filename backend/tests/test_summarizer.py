"""Unit tests for the summarizer service — all Claude API and DB calls are mocked."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)

from services.sources.base import EmailMessage
from services.summarizer import _DEFAULT_PREFS, _call_with_retry, build_prompt, summarize


def _make_email(
    email_id: str = "e1",
    subject: str = "Test Subject",
    sender_name: str = "Alice",
    sender_email: str = "alice@example.com",
    body_preview: str = "Hello there",
    received_at: datetime | None = None,
) -> EmailMessage:
    return EmailMessage(
        id=email_id,
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_preview=body_preview,
        received_at=received_at or datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone.utc),
        is_read=False,
    )


def _make_anthropic_message(text: str, input_tokens: int = 100, output_tokens: int = 200) -> MagicMock:
    """Build a mock anthropic Message response."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return msg


class TestBuildPrompt(unittest.TestCase):

    def test_contains_user_email(self) -> None:
        prompt = build_prompt("user@test.com", "some prefs", [])
        self.assertIn("user@test.com", prompt)

    def test_contains_digest_prefs(self) -> None:
        prefs = "Flag urgent items immediately."
        prompt = build_prompt("u@t.com", prefs, [])
        self.assertIn(prefs, prompt)

    def test_contains_email_subject(self) -> None:
        emails = [_make_email(subject="Project Deadline Tomorrow")]
        prompt = build_prompt("u@t.com", "prefs", emails)
        self.assertIn("Project Deadline Tomorrow", prompt)

    def test_contains_sender_email(self) -> None:
        emails = [_make_email(sender_email="boss@corp.com")]
        prompt = build_prompt("u@t.com", "prefs", emails)
        self.assertIn("boss@corp.com", prompt)

    def test_empty_emails_produces_valid_prompt(self) -> None:
        prompt = build_prompt("u@t.com", "prefs", [])
        self.assertIn("urgent", prompt.lower())
        self.assertIn("action_required", prompt)
        self.assertIn("fyi", prompt)
        self.assertIn("todos", prompt)

    def test_multiple_emails_all_present(self) -> None:
        emails = [
            _make_email(email_id="1", subject="First Email"),
            _make_email(email_id="2", subject="Second Email"),
        ]
        prompt = build_prompt("u@t.com", "prefs", emails)
        self.assertIn("First Email", prompt)
        self.assertIn("Second Email", prompt)

    def test_returns_string(self) -> None:
        result = build_prompt("u@t.com", "prefs", [])
        self.assertIsInstance(result, str)

    def test_output_json_schema_is_described(self) -> None:
        prompt = build_prompt("u@t.com", "prefs", [])
        self.assertIn('"urgent"', prompt)
        self.assertIn('"todos"', prompt)


class TestCallWithRetry(unittest.IsolatedAsyncioTestCase):

    async def test_returns_parsed_digest_on_success(self) -> None:
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_anthropic_message(json.dumps(digest_json), 50, 80)
        )

        result = await _call_with_retry(mock_client, "test prompt")

        self.assertEqual(result["digest"], digest_json)
        self.assertEqual(result["token_usage"]["input_tokens"], 50)
        self.assertEqual(result["token_usage"]["output_tokens"], 80)

    async def test_retries_once_on_malformed_json(self) -> None:
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _make_anthropic_message("not valid json"),
                _make_anthropic_message(json.dumps(digest_json)),
            ]
        )

        result = await _call_with_retry(mock_client, "prompt")

        self.assertEqual(result["digest"], digest_json)
        self.assertEqual(mock_client.messages.create.call_count, 2)

    async def test_raises_after_two_malformed_responses(self) -> None:
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_anthropic_message("{bad json{{")
        )

        with self.assertRaises(ValueError) as ctx:
            await _call_with_retry(mock_client, "prompt")

        self.assertIn("malformed JSON", str(ctx.exception))
        self.assertEqual(mock_client.messages.create.call_count, 2)

    async def test_token_usage_is_logged(self) -> None:
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_anthropic_message(json.dumps(digest_json), 120, 300)
        )

        with self.assertLogs("services.summarizer", level="INFO") as log_ctx:
            await _call_with_retry(mock_client, "prompt")

        self.assertTrue(
            any("input_tokens=120" in line for line in log_ctx.output),
            msg=f"Token usage not logged: {log_ctx.output}",
        )

    async def test_calls_claude_with_correct_model(self) -> None:
        from services.summarizer import MODEL
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_anthropic_message(json.dumps(digest_json))
        )

        await _call_with_retry(mock_client, "prompt")

        call_kwargs = mock_client.messages.create.call_args
        self.assertEqual(call_kwargs.kwargs.get("model") or call_kwargs.args[0], MODEL)

    async def test_calls_claude_with_max_tokens_limit(self) -> None:
        from services.summarizer import MAX_TOKENS
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_anthropic_message(json.dumps(digest_json))
        )

        await _call_with_retry(mock_client, "prompt")

        call_kwargs = mock_client.messages.create.call_args
        self.assertLessEqual(call_kwargs.kwargs.get("max_tokens", MAX_TOKENS), MAX_TOKENS)


class TestSummarize(unittest.IsolatedAsyncioTestCase):

    def _make_user_row(self, user_id: str = "u1", email: str = "user@example.com") -> MagicMock:
        row = MagicMock()
        row.__getitem__ = lambda self, key: email if key == "email" else user_id
        return row

    def _make_settings_row(self, prefs: str = "default prefs") -> MagicMock:
        row = MagicMock()
        row.__getitem__ = lambda self, key: prefs if key == "digest_prefs" else None
        return row

    async def test_uses_digest_prefs_override_when_provided(self) -> None:
        override = "Custom override prefs"
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        captured_prompt: list[str] = []

        async def fake_call(client, prompt: str) -> dict:
            captured_prompt.append(prompt)
            return {"digest": digest_json, "token_usage": {"input_tokens": 10, "output_tokens": 20}}

        with (
            patch("services.summarizer.db.get_user_by_id", return_value=self._make_user_row()),
            patch("services.summarizer.db.get_digest_settings", return_value=self._make_settings_row("stored prefs")),
            patch("services.summarizer._call_with_retry", side_effect=fake_call),
        ):
            await summarize("u1", [], digest_prefs_override=override)

        self.assertIn(override, captured_prompt[0])
        self.assertNotIn("stored prefs", captured_prompt[0])

    async def test_uses_stored_prefs_when_no_override(self) -> None:
        stored = "Stored user preferences"
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        captured_prompt: list[str] = []

        async def fake_call(client, prompt: str) -> dict:
            captured_prompt.append(prompt)
            return {"digest": digest_json, "token_usage": {"input_tokens": 10, "output_tokens": 20}}

        with (
            patch("services.summarizer.db.get_user_by_id", return_value=self._make_user_row()),
            patch("services.summarizer.db.get_digest_settings", return_value=self._make_settings_row(stored)),
            patch("services.summarizer._call_with_retry", side_effect=fake_call),
        ):
            await summarize("u1", [])

        self.assertIn(stored, captured_prompt[0])

    async def test_uses_default_prefs_when_no_settings(self) -> None:
        digest_json = {"urgent": [], "action_required": [], "fyi": [], "todos": []}
        captured_prompt: list[str] = []

        async def fake_call(client, prompt: str) -> dict:
            captured_prompt.append(prompt)
            return {"digest": digest_json, "token_usage": {"input_tokens": 10, "output_tokens": 20}}

        with (
            patch("services.summarizer.db.get_user_by_id", return_value=self._make_user_row()),
            patch("services.summarizer.db.get_digest_settings", return_value=None),
            patch("services.summarizer._call_with_retry", side_effect=fake_call),
        ):
            await summarize("u1", [])

        self.assertIn(_DEFAULT_PREFS[:30], captured_prompt[0])

    async def test_raises_when_user_not_found(self) -> None:
        with patch("services.summarizer.db.get_user_by_id", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                await summarize("missing-user", [])
        self.assertIn("missing-user", str(ctx.exception))

    async def test_returns_digest_and_token_usage(self) -> None:
        digest_json = {
            "urgent": [{"subject": "Urgent!", "sender": "boss", "summary": "s", "reason": "r", "suggested_action": "a"}],
            "action_required": [],
            "fyi": [],
            "todos": [{"item": "Reply to boss", "source_email": "boss@co.com"}],
        }
        expected_usage = {"input_tokens": 150, "output_tokens": 250}

        with (
            patch("services.summarizer.db.get_user_by_id", return_value=self._make_user_row()),
            patch("services.summarizer.db.get_digest_settings", return_value=self._make_settings_row()),
            patch(
                "services.summarizer._call_with_retry",
                return_value={"digest": digest_json, "token_usage": expected_usage},
            ),
        ):
            result = await summarize("u1", [_make_email()])

        self.assertEqual(result["digest"], digest_json)
        self.assertEqual(result["token_usage"], expected_usage)

    async def test_email_list_is_included_in_prompt(self) -> None:
        emails = [_make_email(subject="Critical Bug Report")]
        captured_prompt: list[str] = []

        async def fake_call(client, prompt: str) -> dict:
            captured_prompt.append(prompt)
            return {"digest": {}, "token_usage": {"input_tokens": 0, "output_tokens": 0}}

        with (
            patch("services.summarizer.db.get_user_by_id", return_value=self._make_user_row()),
            patch("services.summarizer.db.get_digest_settings", return_value=self._make_settings_row()),
            patch("services.summarizer._call_with_retry", side_effect=fake_call),
        ):
            await summarize("u1", emails)

        self.assertIn("Critical Bug Report", captured_prompt[0])


if __name__ == "__main__":
    unittest.main()
