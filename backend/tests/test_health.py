import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret")

from starlette.testclient import TestClient

from main import app


class TestHealthEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_returns_200(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_returns_ok_body(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
