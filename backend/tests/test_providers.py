"""Tests for the EmailSource / DigestDestination abstractions and EmailMessage dataclass."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.sources.base import EmailMessage, EmailSource
from services.destinations.base import DigestDestination
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS


class TestEmailSourceABC(unittest.TestCase):
    def test_cannot_instantiate_directly(self) -> None:
        with self.assertRaises(TypeError):
            EmailSource()  # type: ignore[abstract]

    def test_has_required_abstract_methods(self) -> None:
        abstract = EmailSource.__abstractmethods__
        self.assertIn("get_auth_url", abstract)
        self.assertIn("handle_callback", abstract)
        self.assertIn("fetch_emails", abstract)
        self.assertIn("revoke", abstract)


class TestDigestDestinationABC(unittest.TestCase):
    def test_cannot_instantiate_directly(self) -> None:
        with self.assertRaises(TypeError):
            DigestDestination()  # type: ignore[abstract]

    def test_has_required_abstract_methods(self) -> None:
        abstract = DigestDestination.__abstractmethods__
        self.assertIn("connect", abstract)
        self.assertIn("send_digest", abstract)
        self.assertIn("disconnect", abstract)


class TestEmailMessage(unittest.TestCase):
    def test_required_fields(self) -> None:
        now = datetime.now()
        msg = EmailMessage(
            id="abc",
            subject="Hello",
            sender_name="Alice",
            sender_email="alice@example.com",
            body_preview="Hi there",
            received_at=now,
            is_read=False,
        )
        self.assertEqual(msg.id, "abc")
        self.assertEqual(msg.subject, "Hello")
        self.assertEqual(msg.received_at, now)
        self.assertFalse(msg.is_read)

    def test_optional_fields_default_to_none_and_false(self) -> None:
        msg = EmailMessage(
            id="1",
            subject="S",
            sender_name="B",
            sender_email="b@b.com",
            body_preview="",
            received_at=datetime.now(),
            is_read=True,
        )
        self.assertIsNone(msg.conversation_id)
        self.assertFalse(msg.has_attachments)

    def test_optional_fields_can_be_set(self) -> None:
        msg = EmailMessage(
            id="2",
            subject="S",
            sender_name="C",
            sender_email="c@c.com",
            body_preview="preview",
            received_at=datetime.now(),
            is_read=False,
            conversation_id="thread-99",
            has_attachments=True,
        )
        self.assertEqual(msg.conversation_id, "thread-99")
        self.assertTrue(msg.has_attachments)


class TestRegistry(unittest.TestCase):
    def test_source_providers_is_empty_in_phase_0(self) -> None:
        self.assertIsInstance(SOURCE_PROVIDERS, dict)
        self.assertEqual(len(SOURCE_PROVIDERS), 0)

    def test_destination_providers_is_empty_in_phase_0(self) -> None:
        self.assertIsInstance(DESTINATION_PROVIDERS, dict)
        self.assertEqual(len(DESTINATION_PROVIDERS), 0)


if __name__ == "__main__":
    unittest.main()
