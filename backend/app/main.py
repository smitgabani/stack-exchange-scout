import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import (
    accounts,
    auth,
    dashboard,
    definitions,
    digests,
    jobs,
    llm,
    profile,
    questions,
    scout,
    webhooks,
)
from app.api import settings as settings_api
from app.core.config import settings
from app.core.db import get_db
from app.core.security import require_session

# Imported for its side effects: importing it registers the four job workers.
from app.services import (
    job_service,
    job_workers,  # noqa: F401
)

# Without this, nothing the application logs is ever seen. Uvicorn configures
# its own loggers and leaves the root at WARNING, so every logger.info in this
# codebase — enrichment counts, prompt activations, job failures — was being
# dropped. Found when the request-timing line below produced no output while
# its Server-Timing header worked.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """A deploy kills whatever job was mid-flight.

    Say so on the way back up, rather than leaving a row claiming to be
    running — the UI cannot tell that apart from work still in progress, and
    the user waits for something that will never finish.
    """
    await job_service.recover_interrupted()
    yield


app = FastAPI(
    title="Stack Overflow Challenge Scout",
    dependencies=[Depends(require_session)],
    lifespan=lifespan,
)

@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    """One line per request: method, path, status, milliseconds.

    Written because answering "what is slow" meant guessing. Diagnosing the
    connection-pool problem took a measurement script run over SSH against the
    live machine, when the answer should have been in the logs.

    Deliberately not a metrics stack: one structured line is greppable, costs
    a timestamp subtraction, and is enough to find a slow endpoint.
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    # The query string can carry an API key on some settings routes, so only
    # the path is logged.
    logger.info(
        "request path=%s method=%s status=%d ms=%.1f",
        request.url.path,
        request.method,
        response.status_code,
        elapsed_ms,
    )
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(settings_api.router)
app.include_router(scout.router)
app.include_router(definitions.router)
app.include_router(accounts.router)
app.include_router(webhooks.router)
app.include_router(questions.router)
app.include_router(digests.router)
app.include_router(llm.router)
app.include_router(jobs.router)
app.include_router(dashboard.router)


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
