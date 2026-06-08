"""Claude API summarization service — implemented in Phase 3."""
from services.sources.base import EmailMessage


async def build_prompt(user_email: str, digest_prefs: str, emails: list[EmailMessage]) -> str:
    """Assemble the Claude prompt from user prefs and email list."""
    raise NotImplementedError("Implemented in Phase 3")


async def summarize(user_id: str, emails: list[EmailMessage]) -> dict:
    """Call Claude API with assembled prompt; return parsed digest JSON."""
    raise NotImplementedError("Implemented in Phase 3")
