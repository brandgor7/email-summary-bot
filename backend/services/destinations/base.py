from abc import ABC, abstractmethod


class DigestDestination(ABC):
    @abstractmethod
    async def connect(self, user_id: str, config: dict) -> None:
        """Store connection config (e.g. chat_id, webhook URL)."""

    @abstractmethod
    async def send_digest(self, user_id: str, digest: dict) -> None:
        """Format and deliver a digest to this destination."""

    @abstractmethod
    async def disconnect(self, user_id: str) -> None:
        """Remove stored connection config."""
