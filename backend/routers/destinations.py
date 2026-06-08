from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_current_user
from services.registry import DESTINATION_PROVIDERS

router = APIRouter(prefix="/destinations", tags=["destinations"])


@router.post("/{destination_type}/connect")
async def connect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Connect a destination provider — implemented in Phase 4."""
    provider = DESTINATION_PROVIDERS.get(destination_type)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 4")


@router.delete("/{destination_type}/disconnect")
async def disconnect_destination(
    destination_type: str, user: dict = Depends(get_current_user)
) -> dict:
    """Disconnect a destination provider — implemented in Phase 4."""
    provider = DESTINATION_PROVIDERS.get(destination_type)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown destination: {destination_type}",
        )
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 4")
