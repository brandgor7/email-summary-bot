from fastapi import FastAPI

from routers import auth, destinations, digest, users

app = FastAPI(title="email-summary-bot")

app.include_router(auth.router)
app.include_router(digest.router)
app.include_router(destinations.router)
app.include_router(users.router)


@app.get("/health")
async def health() -> dict:
    """Liveness check used by deploy.sh and monitoring."""
    return {"status": "ok"}
