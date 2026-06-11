import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from dependencies import get_current_user
from services.registry import SOURCE_PROVIDERS

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/{source}/url")
async def get_auth_url(
    source: str,
    account_type: str = "personal",
    user: dict = Depends(get_current_user),
) -> dict:
    """Return the OAuth consent URL for the given source provider."""
    provider = SOURCE_PROVIDERS.get(source)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {source}")
    url = await provider.get_auth_url(user["sub"], account_type)
    return {"url": url}


@router.get("/{source}/callback")
async def auth_callback_browser(source: str, code: str, state: str) -> RedirectResponse:
    """Handle browser OAuth redirect — exchanges code, stores tokens, redirects to frontend.

    Microsoft (and other providers) redirect here after the user consents.
    The `state` parameter carries the user_id set in `get_auth_url`.
    No JWT is required here because auth is implicit in completing the OAuth flow.
    """
    provider = SOURCE_PROVIDERS.get(source)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {source}")
    try:
        await provider.handle_callback(state, code)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(url=f"{frontend_url}/onboard?oauth={source}&status=connected")


@router.post("/{source}/callback")
async def auth_callback(source: str, code: str, user: dict = Depends(get_current_user)) -> dict:
    """Handle programmatic OAuth callback (API client flow): exchange code for tokens."""
    provider = SOURCE_PROVIDERS.get(source)
    if not provider:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown source: {source}")
    try:
        await provider.handle_callback(user["sub"], code)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return {"status": "connected"}
