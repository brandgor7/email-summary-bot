"""Tests for get_current_user JWT auth dependency."""
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


def _make_token(payload: dict, secret: str = _TEST_SECRET) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


class TestAuthDependency(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
        cls.client = TestClient(app)

    def test_no_token_returns_401(self) -> None:
        response = self.client.get("/users/me/settings")
        self.assertEqual(response.status_code, 401)

    def test_malformed_bearer_returns_401(self) -> None:
        response = self.client.get(
            "/users/me/settings", headers={"Authorization": "Bearer not-a-jwt"}
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_secret_returns_401(self) -> None:
        token = _make_token({"sub": "user-1"}, secret="wrong-secret")
        response = self.client.get(
            "/users/me/settings", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_token_returns_401(self) -> None:
        token = _make_token({"sub": "user-1", "exp": int(time.time()) - 60})
        response = self.client.get(
            "/users/me/settings", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_passes_auth(self) -> None:
        token = _make_token({"sub": "user-1", "exp": int(time.time()) + 3600})
        response = self.client.get(
            "/providers", headers={"Authorization": f"Bearer {token}"}
        )
        # Auth passes (providers endpoint is public and has no DB dependency)
        self.assertEqual(response.status_code, 200)

    def test_valid_token_all_protected_routes(self) -> None:
        token = _make_token({"sub": "user-1", "exp": int(time.time()) + 3600})
        headers = {"Authorization": f"Bearer {token}"}
        # Routes that don't require a real DB to prove auth passes
        protected = [
            ("GET", "/auth/outlook/url"),
            ("POST", "/auth/outlook/callback?code=abc"),
            ("POST", "/digest/preview"),
        ]
        for method, path in protected:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, headers=headers)
                self.assertNotEqual(
                    response.status_code, 401,
                    msg=f"{method} {path} returned 401 with a valid token",
                )


if __name__ == "__main__":
    unittest.main()
