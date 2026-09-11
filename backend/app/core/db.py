from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# statement_cache_size=0 disables asyncpg's server-side prepared-statement
# cache. Required against Supabase's Transaction-mode pooler (PgBouncer):
# in transaction pooling, consecutive queries aren't guaranteed to hit the
# same underlying Postgres connection, so a statement prepared on one
# connection can't be reused safely on another.
engine = create_async_engine(
    settings.database_url,
    connect_args={"statement_cache_size": 0},
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, closes it when the request ends."""
    async with async_session() as session:
        yield session
