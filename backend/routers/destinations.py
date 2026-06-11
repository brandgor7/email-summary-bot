import logging

from fastapi import APIRouter, Depends, HTTPException, status

import db
from dependencies import get_current_user
from models import TelegramConnectRequest
from services.destinations.telegram import TelegramDestination
from services.registry import DESTINATION_PROVIDERS

router = APIRouter(prefix="/destinations", tags=["destinations"])
logger = logging.getLogger(__name__)

_telegram = TelegramDestination()


# ── Telegram-specific routes ────────────────────────────────────────────────

@router.post("/telegram/connect")
async def telegram_connect(
    req: TelegramConnectRequest, user: dict = Depends(get_current_user)
) -> dict:
    """Link the current user's account to a Telegram chat by chat_id."""
    user_id: str = user["sub"]
    await _telegram.connect(user_id, {"chat_id": int(req.chat_id)})
    return {"linked": True}


@router.get("/telegram/status")
async def telegram_status(user: dict = Depends(get_current_user)) -> dict:
    """Return whether the current user has a linked Telegram chat."""
    user_id: str = user["sub"]
    config = await db.get_destination_config(user_id, "telegram")
    return {"linked": config is not None}


# ── Generic destination routes ───────────────────────────────────────────────

@router.post("/{destination_type}/connect")
async def connect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Connect a destination provider (use POST /destinations/telegram/connect for Telegram)."""
    if not DESTINATION_PROVIDERS.get(destination_type):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Other providers not yet implemented",
    )


@router.delete("/{destination_type}/disconnect")
async def disconnect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Disconnect a destination provider."""
    provider = DESTINATION_PROVIDERS.get(destination_type)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    user_id: str = user["sub"]
    await provider.disconnect(user_id)
    return {"disconnected": destination_type}
