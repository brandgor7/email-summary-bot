import os

import certifi

# Ensure all outbound HTTPS connections (including the Anthropic SDK's internal
# httpx client) use certifi's CA bundle. Must be set before any SSL context is
# created, so it goes before all other imports.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import admin, auth, destinations, digest, users
from services.registry import DESTINATION_PROVIDERS, SOURCE_PROVIDERS


async def _run_migrations() -> None:
    """Apply any schema migrations needed for existing databases."""
    db_path = os.getenv("DB_PATH", "./dev.sqlite")
    async with aiosqlite.connect(db_path) as conn:
        try:
            await conn.execute(
                "ALTER TABLE source_tokens ADD COLUMN account_type TEXT NOT NULL DEFAULT 'personal'"
            )
            await conn.commit()
        except Exception:
            pass  # Column already exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _run_migrations()
    yield


app = FastAPI(title="email-summary-bot", lifespan=lifespan)

frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
