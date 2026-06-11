from pydantic import BaseModel, field_validator


class TelegramConnectRequest(BaseModel):
    chat_id: str

    @field_validator("chat_id")
    @classmethod
    def must_be_numeric(cls, v: str) -> str:
        """Telegram chat IDs are integers; group chats are negative."""
        stripped = v.strip()
        numeric = stripped.lstrip("-")
        if not numeric.isdigit():
            raise ValueError("chat_id must be a numeric Telegram chat ID")
        return stripped


class DigestSettingsResponse(BaseModel):
    digest_prefs: str
    schedule: str
    enabled: bool


class DigestSettingsUpdate(BaseModel):
    digest_prefs: str | None = None
    schedule: str | None = None
    enabled: bool | None = None


class PreviewRequest(BaseModel):
    source: str = "outlook"
    since_hours: int = 24
    digest_prefs_override: str | None = None
    send_to: str | None = None
