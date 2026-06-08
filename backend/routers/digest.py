from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import DefaultDict

from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_current_user
from models import PreviewRequest
from services import summarizer
from services.registry import SOURCE_PROVIDERS

router = APIRouter(prefix="/digest", tags=["digest"])

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


@router.post("/preview")
async def preview_digest(
    req: PreviewRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """On-demand digest preview — fetch emails, summarize, return structured digest."""
    user_id: str = user["sub"]

    _check_rate_limit(user_id)

    if req.source not in SOURCE_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source provider '{req.source}' not registered",
        )

    since = datetime.now(timezone.utc) - timedelta(hours=req.since_hours)
    emails = await SOURCE_PROVIDERS[req.source].fetch_emails(user_id, since=since)

    result = await summarizer.summarize(
        user_id, emails, digest_prefs_override=req.digest_prefs_override
    )
    return result


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_digest() -> dict:
    """Cron-triggered scheduled digest run — implemented in Phase 5."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 5"
    )
