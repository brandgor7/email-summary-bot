"""Tests for AES-256 (Fernet) token encryption helpers."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 64 hex chars = 32 bytes — valid Fernet key material
_TEST_KEY = "a" * 64

# Import once at class setup; patch os.getenv for the missing-key test
import services.token_store as _ts


class TestTokenStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["TOKEN_ENCRYPTION_KEY"] = _TEST_KEY

    def test_encrypt_returns_different_value(self) -> None:
        encrypted = _ts.encrypt("my-secret-token")
        self.assertNotEqual(encrypted, "my-secret-token")

    def test_decrypt_recovers_plaintext(self) -> None:
        plaintext = "refresh_token_value_12345"
        self.assertEqual(_ts.decrypt(_ts.encrypt(plaintext)), plaintext)

    def test_roundtrip_preserves_unicode(self) -> None:
        plaintext = "tøken-with-ünïcödé"
        self.assertEqual(_ts.decrypt(_ts.encrypt(plaintext)), plaintext)

    def test_two_encryptions_of_same_value_differ(self) -> None:
        # Fernet uses a random IV so ciphertexts must differ
        self.assertNotEqual(_ts.encrypt("same-value"), _ts.encrypt("same-value"))

    def test_missing_key_raises_runtime_error(self) -> None:
        with patch("os.getenv", return_value=None):
            with self.assertRaises(RuntimeError):
                _ts.encrypt("anything")


if __name__ == "__main__":
    unittest.main()
