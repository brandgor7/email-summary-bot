"""MS Graph (Outlook) source provider — implemented in Phase 2."""
from datetime import datetime

from services.sources.base import EmailMessage, EmailSource


class OutlookSource(EmailSource):
    async def get_auth_url(self, user_id: str) -> str:
        raise NotImplementedError("Implemented in Phase 2")

    async def handle_callback(self, user_id: str, code: str) -> None:
        raise NotImplementedError("Implemented in Phase 2")

    async def fetch_emails(self, user_id: str, since: datetime | None) -> list[EmailMessage]:
        raise NotImplementedError("Implemented in Phase 2")

    async def revoke(self, user_id: str) -> None:
        raise NotImplementedError("Implemented in Phase 2")
