"""Manual test script for the summarization pipeline — run after completing Phase 3."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.registry import SOURCE_PROVIDERS
from services.summarizer import summarize


async def main() -> None:
    user_id = input("Enter test user_id: ").strip()
    emails = await SOURCE_PROVIDERS["outlook"].fetch_emails(user_id, since=None)
    print(f"Fetched {len(emails)} emails, summarizing...")
    result = await summarize(user_id, emails)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
