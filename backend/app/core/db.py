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
# Pooling. Measured from Fly against the live pooler, per session:
#
#   NullPool (before)          358 ms
#   pool + pre_ping (this)     163 ms
#   pool, no pre_ping           71 ms
#   one query, connection held  25 ms   <- the irreducible round trip
#
# Opening a connection costs ~290ms of TLS handshake and Postgres auth against
# 67ms of actual network distance, and NullPool paid it on every session.
#
# pre_ping costs a further ~92ms — a round trip to ask "are you still there?"
# before handing a connection out. Kept anyway: this app now runs 24/7 and can
# idle for hours, which is exactly when a pooled connection goes stale, and the
# alternative is an intermittent 500 on a request that cannot be retried
# safely. Drop it if 92ms ever matters more than that.
#
# The reason it was NullPool is real: a pooled asyncpg connection belongs to
# the event loop that created it, and reusing it on another loop raises
# "attached to a different loop". Two things killed loops here — Fly stopping
# the machine between requests, and each test building its own.
#
# `min_machines_running = 1` in fly.toml removes the first. The second is not
# fixable, because a fresh loop per test is how pytest-anyio works — so the
# suite keeps NullPool via `db_pool`, which costs it nothing now that it runs
# against local Postgres where a connection is sub-millisecond.
#
# pool_pre_ping checks a connection is alive before handing it out, so one
# that died while idle is replaced rather than raising. pool_recycle keeps
# connections younger than PgBouncer's own idle timeout.
engine = create_async_engine(
    settings.database_url,
    connect_args={"statement_cache_size": 0},
    poolclass=pool.NullPool if settings.db_pool == "null" else pool.AsyncAdaptedQueuePool,
    **(
        {}
        if settings.db_pool == "null"
        else {
            "pool_size": 5,
            "max_overflow": 5,
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    ),
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, closes it when the request ends."""
    async with async_session() as session:
        yield session
