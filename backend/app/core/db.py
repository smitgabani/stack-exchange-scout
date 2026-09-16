from collections.abc import AsyncGenerator

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# statement_cache_size=0 disables asyncpg's server-side prepared-statement
# cache. Required against Supabase's Transaction-mode pooler (PgBouncer):
# in transaction pooling, consecutive queries aren't guaranteed to hit the
# same underlying Postgres connection, so a statement prepared on one
# connection can't be reused safely on another.
#
# poolclass=NullPool: a locally-pooled asyncpg connection is tied to the
# event loop it was created on. Fly's start/stop machine cycle and (for
# tests) each fresh TestClient spinning up its own loop both mean a pooled
# connection can outlive its loop, causing "another operation is in
# progress" errors. PgBouncer already pools upstream, so a fresh physical
# connection per checkout costs little and avoids that class of bug.
engine = create_async_engine(
    settings.database_url,
    connect_args={"statement_cache_size": 0},
    poolclass=pool.NullPool,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, closes it when the request ends."""
    async with async_session() as session:
        yield session
