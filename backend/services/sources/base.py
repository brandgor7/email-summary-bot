from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class TokenRefreshError(Exception):
    """Raised when an OAuth token refresh fails (e.g. token revoked or expired)."""


@dataclass
class EmailMessage:
    id: str
    subject: str
    sender_name: str
    sender_email: str
    body_preview: str
    received_at: datetime
    is_read: bool
    conversation_id: str | None = None
    has_attachments: bool = False


class EmailSource(ABC):
    @abstractmethod
    async def get_auth_url(self, user_id: str) -> str:
        """Return OAuth consent URL for this provider."""

    @abstractmethod
    async def handle_callback(self, user_id: str, code: str) -> None:
        """Exchange auth code for tokens and store them."""

    @abstractmethod
    async def fetch_emails(self, user_id: str, since: datetime | None) -> list[EmailMessage]:
        """Fetch emails since the given datetime."""

    @abstractmethod
    async def revoke(self, user_id: str) -> None:
        """Revoke access and delete stored tokens."""
