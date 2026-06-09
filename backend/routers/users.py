from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

import db
from dependencies import get_current_user
from models import DigestSettingsResponse, DigestSettingsUpdate
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/settings", response_model=DigestSettingsResponse)
async def get_settings(user: dict = Depends(get_current_user)) -> DigestSettingsResponse:
    """Fetch the current user's digest settings."""
    user_id: str = user["sub"]
    email: str = user.get("email", user_id)

    await db.upsert_user(user_id, email, datetime.now(timezone.utc).isoformat())
    await db.upsert_digest_settings(user_id)
    row = await db.get_digest_settings(user_id)
    return DigestSettingsResponse(
        digest_prefs=row["digest_prefs"],
        schedule=row["schedule"],
        enabled=bool(row["enabled"]),
    )


@router.put("/me/settings", response_model=DigestSettingsResponse)
async def update_settings(
    body: DigestSettingsUpdate, user: dict = Depends(get_current_user)
) -> DigestSettingsResponse:
    """Update the current user's digest settings."""
    user_id: str = user["sub"]
    email: str = user.get("email", user_id)

    await db.upsert_user(user_id, email, datetime.now(timezone.utc).isoformat())

    if body.schedule is not None and body.schedule not in ("morning", "evening", "both"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="schedule must be 'morning', 'evening', or 'both'",
        )

    await db.upsert_digest_settings(
        user_id,
        digest_prefs=body.digest_prefs,
        schedule=body.schedule,
        enabled=int(body.enabled) if body.enabled is not None else None,
    )
    row = await db.get_digest_settings(user_id)
    return DigestSettingsResponse(
        digest_prefs=row["digest_prefs"],
        schedule=row["schedule"],
        enabled=bool(row["enabled"]),
    )


@router.get("/me/sources")
async def list_sources(user: dict = Depends(get_current_user)) -> list[dict]:
    """List the current user's connected email sources (provider and email only, no tokens)."""
    user_id: str = user["sub"]
    rows = await db.get_all_source_tokens_for_user(user_id)
    return [{"provider": r["provider"], "provider_email": r["provider_email"]} for r in rows]


@router.get("/me/destinations")
async def list_destinations(user: dict = Depends(get_current_user)) -> list[dict]:
    """List the current user's connected destinations (provider only, no config secrets)."""
    user_id: str = user["sub"]
    rows = await db.get_all_destination_configs_for_user(user_id)
    return [{"provider": r["provider"]} for r in rows]


@router.delete("/me/sources/{provider}", status_code=status.HTTP_200_OK)
async def disconnect_source(
    provider: str, user: dict = Depends(get_current_user)
) -> dict:
    """Revoke and remove a connected email source."""
    if provider not in SOURCE_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown source provider: {provider}",
        )
    user_id: str = user["sub"]
    await SOURCE_PROVIDERS[provider].revoke(user_id)
    return {"disconnected": provider}


@router.delete("/me/destinations/{provider}", status_code=status.HTTP_200_OK)
async def disconnect_destination(
    provider: str, user: dict = Depends(get_current_user)
) -> dict:
    """Disconnect and remove a connected destination."""
    if provider not in DESTINATION_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination provider: {provider}",
        )
    user_id: str = user["sub"]
    await DESTINATION_PROVIDERS[provider].disconnect(user_id)
    return {"disconnected": provider}
