"""Tests for AES-256 (Fernet) token encryption helpers."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a fixed 32-byte hex key for tests
_TEST_KEY = "a" * 64  # 64 hex chars = 32 bytes


class TestTokenStore(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["TOKEN_ENCRYPTION_KEY"] = _TEST_KEY
        # Re-import each test so env is picked up fresh
        import importlib
        import services.token_store as ts
        importlib.reload(ts)
        self.ts = ts

    def test_encrypt_returns_different_value(self) -> None:
        encrypted = self.ts.encrypt("my-secret-token")
        self.assertNotEqual(encrypted, "my-secret-token")

    def test_decrypt_recovers_plaintext(self) -> None:
        plaintext = "refresh_token_value_12345"
        encrypted = self.ts.encrypt(plaintext)
        self.assertEqual(self.ts.decrypt(encrypted), plaintext)

    def test_roundtrip_preserves_unicode(self) -> None:
        plaintext = "tøken-with-ünïcödé"
        self.assertEqual(self.ts.decrypt(self.ts.encrypt(plaintext)), plaintext)

    def test_two_encryptions_of_same_value_differ(self) -> None:
        # Fernet uses a random IV so ciphertexts should differ
        enc1 = self.ts.encrypt("same-value")
        enc2 = self.ts.encrypt("same-value")
        self.assertNotEqual(enc1, enc2)

    def test_missing_key_raises_runtime_error(self) -> None:
        saved = os.environ.pop("TOKEN_ENCRYPTION_KEY", None)
        try:
            import importlib
            import services.token_store as ts
            importlib.reload(ts)
            with self.assertRaises(RuntimeError):
                ts.encrypt("anything")
        finally:
            if saved is not None:
                os.environ["TOKEN_ENCRYPTION_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
