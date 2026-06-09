from pydantic import BaseModel


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
