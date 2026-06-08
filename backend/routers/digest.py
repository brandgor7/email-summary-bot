from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_current_user

router = APIRouter(prefix="/digest", tags=["digest"])


@router.post("/preview")
async def preview_digest(user: dict = Depends(get_current_user)) -> dict:
    """On-demand digest preview — implemented in Phase 3."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 3")


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_digest() -> dict:
    """Cron-triggered scheduled digest run — implemented in Phase 5."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Implemented in Phase 5")
