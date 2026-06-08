from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_current_user
from models import DigestSettingsResponse, DigestSettingsUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/settings", response_model=DigestSettingsResponse)
async def get_settings(user: dict = Depends(get_current_user)) -> DigestSettingsResponse:
    """Fetch the current user's digest settings — implemented in Phase 6."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 6")


@router.put("/me/settings", response_model=DigestSettingsResponse)
async def update_settings(
    body: DigestSettingsUpdate, user: dict = Depends(get_current_user)
) -> DigestSettingsResponse:
    """Update the current user's digest settings — implemented in Phase 6."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 6")
