from fastapi import FastAPI

from routers import admin, auth, destinations, digest, users
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS

app = FastAPI(title="email-summary-bot")

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(digest.router)
app.include_router(destinations.router)
app.include_router(users.router)


@app.get("/health")
async def health() -> dict:
    """Liveness check used by deploy.sh and monitoring."""
    return {"status": "ok"}


@app.get("/providers")
async def list_providers() -> dict:
    """Return the registered source and destination provider keys — no auth required."""
    return {
        "sources": list(SOURCE_PROVIDERS.keys()),
        "destinations": list(DESTINATION_PROVIDERS.keys()),
    }
