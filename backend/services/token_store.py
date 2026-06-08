import base64
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    """Load the encryption key from env and return a Fernet instance."""
    raw_key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    key_bytes = bytes.fromhex(raw_key)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string with AES-256 (Fernet) and return a base64 token."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token and return the original string."""
    return _get_fernet().decrypt(token.encode()).decode()
