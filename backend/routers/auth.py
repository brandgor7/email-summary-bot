from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_current_user
from services.registry import SOURCE_PROVIDERS

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/{source}/url")
async def get_auth_url(source: str, user: dict = Depends(get_current_user)) -> dict:
    """Return the OAuth consent URL for the given source provider."""
    provider = SOURCE_PROVIDERS.get(source)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {source}")
    url = await provider.get_auth_url(user["sub"])
    return {"url": url}


@router.post("/{source}/callback")
async def auth_callback(source: str, code: str, user: dict = Depends(get_current_user)) -> dict:
    """Handle OAuth callback: exchange code for tokens and store them."""
    provider = SOURCE_PROVIDERS.get(source)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {source}")
    await provider.handle_callback(user["sub"], code)
    return {"status": "connected"}
