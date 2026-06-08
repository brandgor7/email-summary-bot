"""Manual test script for the Outlook email fetch — run after completing Phase 2."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.registry import SOURCE_PROVIDERS


async def main() -> None:
    user_id = input("Enter test user_id: ").strip()
    emails = await SOURCE_PROVIDERS["outlook"].fetch_emails(user_id, since=None)
    print(f"Fetched {len(emails)} emails")
    for email in emails[:3]:
        print(email)


if __name__ == "__main__":
    asyncio.run(main())
