from fastapi import FastAPI

app = FastAPI(title="email-summary-bot")


@app.get("/health")
async def health() -> dict:
    """Liveness check used by deploy.sh and monitoring."""
    return {"status": "ok"}
