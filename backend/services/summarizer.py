"""Claude API summarization service."""
import json
import logging
import os

import anthropic

import db
from services.sources.base import EmailMessage

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2000

_DEFAULT_PREFS = (
    "Flag as urgent if someone is waiting on my response or there is a deadline mentioned. "
    "Create a todo if I owe someone something or have an action item. "
    "Group emails by inferred project or topic if you can determine one; "
    "otherwise group by sender domain."
)

# Edit this constant to change the prompt sent to Claude.
# {{user_email}}, {{digest_prefs}}, and {{emails_json}} are substituted at runtime.
_PROMPT_TEMPLATE = """\
You are an intelligent email digest assistant for {{user_email}}.

USER PREFERENCES:
{{digest_prefs}}

Given the following emails (JSON), produce a structured digest with:
1. URGENT — emails needing action today (sorted by urgency)
2. ACTION REQUIRED — emails needing a response but not urgent
3. FYI — informational, no action needed
4. TODO LIST — a deduplicated list of action items the user needs to take

For each email include:
- Subject and sender
- One-sentence summary
- Why it's in this category
- Suggested reply or action (if applicable)

Output ONLY valid JSON matching this schema:
{
  "urgent": [{"subject": "str", "sender": "str", "summary": "str", "reason": "str", "suggested_action": "str"}],
  "action_required": [{"subject": "str", "sender": "str", "summary": "str", "reason": "str", "suggested_action": "str"}],
  "fyi": [{"subject": "str", "sender": "str", "summary": "str"}],
  "todos": [{"item": "str", "source_email": "str"}]
}

Emails:
{{emails_json}}"""


def build_prompt(user_email: str, digest_prefs: str, emails: list[EmailMessage]) -> str:
    """Assemble the Claude prompt from user prefs and email list."""
    emails_data = [
        {
            "id": e.id,
            "subject": e.subject,
            "sender_name": e.sender_name,
            "sender_email": e.sender_email,
            "body_preview": e.body_preview,
            "received_at": e.received_at.isoformat(),
            "is_read": e.is_read,
            "conversation_id": e.conversation_id,
            "has_attachments": e.has_attachments,
        }
        for e in emails
    ]
    emails_json = json.dumps(emails_data, indent=2)

    return (
        _PROMPT_TEMPLATE
        .replace("{{user_email}}", user_email)
        .replace("{{digest_prefs}}", digest_prefs)
        .replace("{{emails_json}}", emails_json)
    )


async def summarize(
    user_id: str,
    emails: list[EmailMessage],
    digest_prefs_override: str | None = None,
) -> dict:
    """Call Claude API with assembled prompt; return parsed digest JSON and token usage."""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    settings = await db.get_digest_settings(user_id)
    if digest_prefs_override is not None:
        digest_prefs = digest_prefs_override
    elif settings is not None:
        digest_prefs = settings["digest_prefs"]
    else:
        digest_prefs = _DEFAULT_PREFS

    prompt = build_prompt(user["email"], digest_prefs, emails)

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return await _call_with_retry(client, prompt)


async def _call_with_retry(client: anthropic.AsyncAnthropic, prompt: str) -> dict:
    """Call Claude API and parse JSON response, retrying once on parse failure."""
    last_exc: Exception | None = None
    for attempt in range(2):
        message = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        logger.info(
            "Claude usage: input_tokens=%d output_tokens=%d", input_tokens, output_tokens
        )

        raw = message.content[0].text
        try:
            digest = json.loads(raw)
            return {
                "digest": digest,
                "token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            }
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("Claude returned malformed JSON on attempt 1, retrying...")

    logger.error("Claude returned malformed JSON after retry")
    raise ValueError("Model returned malformed JSON after retry") from last_exc
