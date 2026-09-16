from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db

app = FastAPI(title="Stack Overflow Challenge Scout")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check: is the process up at all? No dependencies checked."""
    return {"status": "ok"}


@app.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Readiness check: is the process actually able to serve traffic?

    Right now that just means "can it reach the database" — this is what
    proves the Supabase connection string is real and working.
    """
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
