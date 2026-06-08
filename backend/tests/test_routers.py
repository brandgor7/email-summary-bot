"""Tests for router-level behaviour: 401 without auth, 404 for unknown providers."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_SECRET = "test-nextauth-secret"
os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
os.environ.setdefault("DB_PATH", ":memory:")

import jwt
from starlette.testclient import TestClient

from main import app


def _valid_token() -> str:
    return jwt.encode(
        {"sub": "user-test", "exp": int(time.time()) + 3600},
        _TEST_SECRET,
        algorithm="HS256",
    )


class TestRouteProtection(unittest.TestCase):
    """Every user-facing route must return 401 when no token is provided."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _assert_401_without_token(self, method: str, path: str) -> None:
        response = self.client.request(method, path)
        self.assertEqual(
            response.status_code, 401,
            msg=f"Expected 401 for {method} {path} without token, got {response.status_code}",
        )

    def test_get_auth_url_requires_token(self) -> None:
        self._assert_401_without_token("GET", "/auth/outlook/url")

    def test_post_auth_callback_requires_token(self) -> None:
        self._assert_401_without_token("POST", "/auth/outlook/callback?code=x")

    def test_post_digest_preview_requires_token(self) -> None:
        self._assert_401_without_token("POST", "/digest/preview")

    def test_get_user_settings_requires_token(self) -> None:
        self._assert_401_without_token("GET", "/users/me/settings")

    def test_put_user_settings_requires_token(self) -> None:
        self._assert_401_without_token("PUT", "/users/me/settings")

    def test_post_destinations_connect_requires_token(self) -> None:
        self._assert_401_without_token("POST", "/destinations/telegram/connect")


class TestUnknownProviders(unittest.TestCase):
    """Routes that look up a provider in the registry return 404 for unknown names."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {_valid_token()}"}

    def test_unknown_source_get_url_returns_404(self) -> None:
        response = self.client.get("/auth/nonexistent/url", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_unknown_source_callback_returns_404(self) -> None:
        response = self.client.post(
            "/auth/nonexistent/callback?code=abc", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_destination_connect_returns_404(self) -> None:
        response = self.client.post(
            "/destinations/nonexistent/connect", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_destination_disconnect_returns_404(self) -> None:
        response = self.client.delete(
            "/destinations/nonexistent/disconnect", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)


class TestCronEndpointNoAuth(unittest.TestCase):
    """/digest/run is not user-authenticated — it uses X-Cron-Secret (Phase 5)."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_digest_run_is_not_jwt_protected(self) -> None:
        # Should not return 401 (will return 501 until Phase 5)
        response = self.client.post("/digest/run")
        self.assertNotEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
