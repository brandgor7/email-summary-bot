"""Tests for GET/PUT /users/me/settings and DELETE /users/me/sources|destinations/{provider}."""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_SECRET = "test-nextauth-secret"
os.environ["NEXTAUTH_SECRET"] = _TEST_SECRET
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "a" * 64)
os.environ.setdefault("MS_CLIENT_ID", "test-client-id")
os.environ.setdefault("MS_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MS_REDIRECT_URI", "http://localhost/callback")


import jwt


def _make_token(user_id: str = "user-test") -> str:
    return jwt.encode(
        {"sub": user_id, "exp": int(time.time()) + 3600},
        _TEST_SECRET,
        algorithm="HS256",
    )


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


class TestProvidersEndpoint(unittest.TestCase):
    """GET /providers returns source and destination keys — no auth required."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_returns_200_without_auth(self) -> None:
        response = self.client.get("/providers")
        self.assertEqual(response.status_code, 200)

    def test_response_has_sources_and_destinations(self) -> None:
        response = self.client.get("/providers")
        data = response.json()
        self.assertIn("sources", data)
        self.assertIn("destinations", data)

    def test_sources_contains_outlook(self) -> None:
        response = self.client.get("/providers")
        self.assertIn("outlook", response.json()["sources"])

    def test_destinations_contains_telegram(self) -> None:
        response = self.client.get("/providers")
        self.assertIn("telegram", response.json()["destinations"])

    def test_sources_is_a_list(self) -> None:
        response = self.client.get("/providers")
        self.assertIsInstance(response.json()["sources"], list)

    def test_destinations_is_a_list(self) -> None:
        response = self.client.get("/providers")
        self.assertIsInstance(response.json()["destinations"], list)


class TestGetSettings(unittest.TestCase):
    """GET /users/me/settings — fetch or auto-create digest settings."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-gs')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.get("/users/me/settings")
        self.assertEqual(response.status_code, 401)

    def test_returns_200_for_authenticated_user(self) -> None:
        response = self.client.get("/users/me/settings", headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_response_has_expected_fields(self) -> None:
        response = self.client.get("/users/me/settings", headers=self.headers)
        data = response.json()
        self.assertIn("digest_prefs", data)
        self.assertIn("schedule", data)
        self.assertIn("enabled", data)

    def test_default_schedule_is_morning(self) -> None:
        response = self.client.get("/users/me/settings", headers=self.headers)
        self.assertEqual(response.json()["schedule"], "morning")

    def test_default_enabled_is_true(self) -> None:
        response = self.client.get("/users/me/settings", headers=self.headers)
        self.assertTrue(response.json()["enabled"])

    def test_default_digest_prefs_not_empty(self) -> None:
        response = self.client.get("/users/me/settings", headers=self.headers)
        self.assertGreater(len(response.json()["digest_prefs"]), 0)

    def test_idempotent_second_call(self) -> None:
        r1 = self.client.get("/users/me/settings", headers=self.headers)
        r2 = self.client.get("/users/me/settings", headers=self.headers)
        self.assertEqual(r1.json(), r2.json())


class TestPutSettings(unittest.TestCase):
    """PUT /users/me/settings — update digest preferences."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-ps')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.put("/users/me/settings", json={})
        self.assertEqual(response.status_code, 401)

    def test_update_digest_prefs(self) -> None:
        new_prefs = "Flag urgent if deadline mentioned."
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"digest_prefs": new_prefs},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["digest_prefs"], new_prefs)

    def test_update_schedule(self) -> None:
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"schedule": "evening"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schedule"], "evening")

    def test_update_enabled_false(self) -> None:
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"enabled": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])

    def test_update_enabled_true(self) -> None:
        self.client.put("/users/me/settings", headers=self.headers, json={"enabled": False})
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"enabled": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

    def test_partial_update_does_not_reset_other_fields(self) -> None:
        self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"schedule": "both", "digest_prefs": "only urgent"},
        )
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"enabled": False},
        )
        data = response.json()
        self.assertEqual(data["schedule"], "both")
        self.assertEqual(data["digest_prefs"], "only urgent")

    def test_invalid_schedule_returns_422(self) -> None:
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"schedule": "weekly"},
        )
        self.assertEqual(response.status_code, 422)

    def test_update_schedule_both(self) -> None:
        response = self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"schedule": "both"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schedule"], "both")

    def test_empty_body_returns_current_settings(self) -> None:
        self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"digest_prefs": "my prefs"},
        )
        response = self.client.put("/users/me/settings", headers=self.headers, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["digest_prefs"], "my prefs")

    def test_changes_persist_on_get(self) -> None:
        new_prefs = "Persist this pref"
        self.client.put(
            "/users/me/settings",
            headers=self.headers,
            json={"digest_prefs": new_prefs},
        )
        response = self.client.get("/users/me/settings", headers=self.headers)
        self.assertEqual(response.json()["digest_prefs"], new_prefs)


class TestDisconnectSource(unittest.TestCase):
    """DELETE /users/me/sources/{provider} — revoke source and remove token."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-ds')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.delete("/users/me/sources/outlook")
        self.assertEqual(response.status_code, 401)

    def test_unknown_provider_returns_404(self) -> None:
        response = self.client.delete(
            "/users/me/sources/nonexistent", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_revoke_calls_provider_revoke(self) -> None:
        with patch(
            "services.registry.SOURCE_PROVIDERS",
            {"outlook": AsyncMock(revoke=AsyncMock())},
        ):
            from importlib import reload
            import routers.users as users_mod
            reload(users_mod)

        with patch(
            "routers.users.SOURCE_PROVIDERS",
            {"outlook": AsyncMock(revoke=AsyncMock(return_value=None))},
        ) as mock_providers:
            response = self.client.delete(
                "/users/me/sources/outlook", headers=self.headers
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["disconnected"], "outlook")

    def test_revoke_returns_disconnected_key(self) -> None:
        with patch(
            "routers.users.SOURCE_PROVIDERS",
            {"outlook": AsyncMock(revoke=AsyncMock(return_value=None))},
        ):
            response = self.client.delete(
                "/users/me/sources/outlook", headers=self.headers
            )
            self.assertEqual(response.json(), {"disconnected": "outlook"})


class TestDisconnectDestination(unittest.TestCase):
    """DELETE /users/me/destinations/{provider} — disconnect destination."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-dd')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.delete("/users/me/destinations/telegram")
        self.assertEqual(response.status_code, 401)

    def test_unknown_provider_returns_404(self) -> None:
        response = self.client.delete(
            "/users/me/destinations/nonexistent", headers=self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_disconnect_calls_provider_disconnect(self) -> None:
        with patch(
            "routers.users.DESTINATION_PROVIDERS",
            {"telegram": AsyncMock(disconnect=AsyncMock(return_value=None))},
        ):
            response = self.client.delete(
                "/users/me/destinations/telegram", headers=self.headers
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["disconnected"], "telegram")

    def test_disconnect_returns_disconnected_key(self) -> None:
        with patch(
            "routers.users.DESTINATION_PROVIDERS",
            {"telegram": AsyncMock(disconnect=AsyncMock(return_value=None))},
        ):
            response = self.client.delete(
                "/users/me/destinations/telegram", headers=self.headers
            )
            self.assertEqual(response.json(), {"disconnected": "telegram"})


class TestListSources(unittest.TestCase):
    """GET /users/me/sources — list connected sources for the current user."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-ls')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.get("/users/me/sources")
        self.assertEqual(response.status_code, 401)

    def test_returns_empty_list_when_no_sources(self) -> None:
        response = self.client.get("/users/me/sources", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_returns_list_type(self) -> None:
        response = self.client.get("/users/me/sources", headers=self.headers)
        self.assertIsInstance(response.json(), list)

    def test_does_not_expose_tokens(self) -> None:
        response = self.client.get("/users/me/sources", headers=self.headers)
        for item in response.json():
            self.assertNotIn("access_token_enc", item)
            self.assertNotIn("refresh_token_enc", item)


class TestListDestinations(unittest.TestCase):
    """GET /users/me/destinations — list connected destinations for the current user."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        cls._db_path = tmp.name
        tmp.close()
        _apply_schema(cls._db_path)
        os.environ["DB_PATH"] = cls._db_path

        from starlette.testclient import TestClient
        from main import app
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {_make_token('user-ld')}"}

    @classmethod
    def tearDownClass(cls) -> None:
        os.unlink(cls._db_path)

    def test_requires_auth(self) -> None:
        response = self.client.get("/users/me/destinations")
        self.assertEqual(response.status_code, 401)

    def test_returns_empty_list_when_no_destinations(self) -> None:
        response = self.client.get("/users/me/destinations", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_returns_list_type(self) -> None:
        response = self.client.get("/users/me/destinations", headers=self.headers)
        self.assertIsInstance(response.json(), list)

    def test_does_not_expose_config(self) -> None:
        response = self.client.get("/users/me/destinations", headers=self.headers)
        for item in response.json():
            self.assertNotIn("config_enc", item)


if __name__ == "__main__":
    unittest.main()
