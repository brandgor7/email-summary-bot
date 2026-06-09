import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import DefaultDict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

import db
from dependencies import get_current_user
from models import PreviewRequest
from services import summarizer
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS
from services.sources.base import EmailMessage

router = APIRouter(prefix="/digest", tags=["digest"])
logger = logging.getLogger(__name__)

_RATE_LIMIT = 10
_RATE_WINDOW_SECONDS = 3600

_preview_timestamps: DefaultDict[str, list[float]] = defaultdict(list)


def _check_rate_limit(user_id: str) -> None:
    """Enforce 10 calls per user per hour; raises 429 if exceeded."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - _RATE_WINDOW_SECONDS
    _preview_timestamps[user_id] = [
        t for t in _preview_timestamps[user_id] if t > cutoff
    ]
    if len(_preview_timestamps[user_id]) >= _RATE_LIMIT:
        oldest = min(_preview_timestamps[user_id])
        retry_after = int(oldest + _RATE_WINDOW_SECONDS - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: 10 preview calls per hour",
            headers={"Retry-After": str(retry_after)},
        )
    _preview_timestamps[user_id].append(now)


def _determine_schedule_slot() -> str:
    """Return 'morning' or 'evening' based on current UTC hour."""
    hour = datetime.now(timezone.utc).hour
    return "morning" if hour < 12 else "evening"


async def _process_single_user(user_id: str, run_at: str) -> None:
    """Fetch, summarize, and deliver digest for one user. All errors are isolated."""
    settings = await db.get_digest_settings(user_id)
    if not settings:
        return

    last_run_at: str | None = settings["last_run_at"]
    if last_run_at:
        since = datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Fetch from all configured sources; track per-provider email counts
    source_tokens = await db.get_all_source_tokens_for_user(user_id)
    email_counts: dict[str, int] = {}
    merged: dict[str, EmailMessage] = {}  # keyed by email id for dedup

    for token_row in source_tokens:
        provider: str = token_row["provider"]
        if provider not in SOURCE_PROVIDERS:
            continue
        try:
            emails = await SOURCE_PROVIDERS[provider].fetch_emails(user_id, since=since)
            email_counts[provider] = len(emails)
            for email in emails:
                if email.id not in merged:
                    merged[email.id] = email
        except Exception as exc:
            logger.error("Source fetch failed user=%s provider=%s: %s", user_id, provider, exc)
            email_counts[provider] = 0

    if not email_counts:
        return

    dest_configs = await db.get_all_destination_configs_for_user(user_id)
    active_dests = [
        r["provider"] for r in dest_configs if r["provider"] in DESTINATION_PROVIDERS
    ]

    if not active_dests:
        return

    merged_emails = list(merged.values())

    if not merged_emails:
        await db.update_last_run(user_id, run_at, None)
        for source_provider in email_counts:
            for dest_provider in active_dests:
                await db.insert_digest_run(
                    run_id=str(uuid.uuid4()),
                    user_id=user_id,
                    source=source_provider,
                    destination=dest_provider,
                    run_at=run_at,
                    email_count=0,
                    status="empty",
                    error_msg=None,
                    tokens_used=None,
                )
        return

    try:
        result = await summarizer.summarize(user_id, merged_emails)
    except Exception as exc:
        logger.error("Summarization failed user=%s: %s", user_id, exc)
        for source_provider, count in email_counts.items():
            for dest_provider in active_dests:
                await db.insert_digest_run(
                    run_id=str(uuid.uuid4()),
                    user_id=user_id,
                    source=source_provider,
                    destination=dest_provider,
                    run_at=run_at,
                    email_count=count,
                    status="error",
                    error_msg=str(exc),
                    tokens_used=None,
                )
        return

    digest = result["digest"]
    tokens_used: int = (
        result["token_usage"]["input_tokens"] + result["token_usage"]["output_tokens"]
    )
    last_email_id: str = merged_emails[0].id

    for dest_provider in active_dests:
        try:
            await DESTINATION_PROVIDERS[dest_provider].send_digest(user_id, digest)
            send_status = "success"
            send_error: str | None = None
        except Exception as exc:
            logger.error("Delivery failed user=%s dest=%s: %s", user_id, dest_provider, exc)
            send_status = "error"
            send_error = str(exc)

        for source_provider, count in email_counts.items():
            await db.insert_digest_run(
                run_id=str(uuid.uuid4()),
                user_id=user_id,
                source=source_provider,
                destination=dest_provider,
                run_at=run_at,
                email_count=count,
                status=send_status,
                error_msg=send_error,
                tokens_used=tokens_used,
            )

    await db.update_last_run(user_id, run_at, last_email_id)


async def _run_digest_for_all_users(schedule_slot: str) -> None:
    """Background task: process digest for every enabled user in the given schedule slot."""
    run_at = datetime.now(timezone.utc).isoformat()
    users = await db.get_enabled_users_for_schedule(schedule_slot)
    for user_row in users:
        user_id: str = user_row["user_id"]
        try:
            await _process_single_user(user_id, run_at)
        except Exception as exc:
            logger.error("Unexpected error processing user=%s: %s", user_id, exc)


@router.post("/preview")
async def preview_digest(
    req: PreviewRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """On-demand digest preview — fetch emails, summarize, optionally send to a destination."""
    user_id: str = user["sub"]

    _check_rate_limit(user_id)

    if req.source not in SOURCE_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source provider '{req.source}' not registered",
        )

    if req.send_to is not None and req.send_to not in DESTINATION_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination provider '{req.send_to}' not registered",
        )

    since = datetime.now(timezone.utc) - timedelta(hours=req.since_hours)
    emails = await SOURCE_PROVIDERS[req.source].fetch_emails(user_id, since=since)

    summarizer_result = await summarizer.summarize(
        user_id, emails, digest_prefs_override=req.digest_prefs_override
    )
    result: dict = dict(summarizer_result)

    if req.send_to is not None:
        try:
            await DESTINATION_PROVIDERS[req.send_to].send_digest(user_id, result["digest"])
            result["send_result"] = {"status": "sent", "destination": req.send_to}
        except Exception as exc:
            logger.error("Send preview failed user=%s dest=%s: %s", user_id, req.send_to, exc)
            result["send_result"] = {"status": "error", "destination": req.send_to, "error": str(exc)}

    return result


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_digest(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Cron-triggered scheduled digest — validates cron secret, returns 202 immediately."""
    cron_secret = os.getenv("CRON_SECRET")
    provided = request.headers.get("X-Cron-Secret")
    if not cron_secret or provided != cron_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing cron secret",
        )
    slot = _determine_schedule_slot()
    background_tasks.add_task(_run_digest_for_all_users, slot)
    return {"status": "accepted", "schedule_slot": slot}
