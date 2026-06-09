import os

from fastapi import APIRouter, HTTPException, Request, status

import db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def admin_stats(request: Request) -> dict:
    """Aggregate digest run stats. Protected by X-Admin-Secret header."""
    admin_secret = os.getenv("ADMIN_SECRET")
    provided = request.headers.get("X-Admin-Secret")
    if not admin_secret or provided != admin_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin secret",
        )
    return await db.get_admin_stats()
