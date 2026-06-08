"""Telegram Bot API destination provider — implemented in Phase 4."""
from services.destinations.base import DigestDestination


class TelegramDestination(DigestDestination):
    async def connect(self, user_id: str, config: dict) -> None:
        raise NotImplementedError("Implemented in Phase 4")

    async def send_digest(self, user_id: str, digest: dict) -> None:
        raise NotImplementedError("Implemented in Phase 4")

    async def disconnect(self, user_id: str) -> None:
        raise NotImplementedError("Implemented in Phase 4")
