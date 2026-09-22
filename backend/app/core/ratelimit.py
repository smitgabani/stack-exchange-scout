"""A ceiling on the endpoints that spend money.

Every job here costs a real LLM call, and a scout run costs $0.35. Nothing
stopped a stuck retry loop — or a double-click — from spending repeatedly, and
the only evidence would have been the bill.

In-process counters rather than Redis. The app runs as a single machine that no
longer scales to zero, so one process sees every request; a second machine would
make this per-machine rather than global, which is the point at which it should
move to the database. Said here so that is a decision rather than a surprise.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

# Generous on purpose: this is a backstop against a loop, not a quota. A person
# clicking buttons will never reach it.
_LIMITS: dict[str, tuple[int, int]] = {
    # name: (max calls, per seconds)
    "llm": (20, 60 * 60),
    "scout_run": (10, 60 * 60),
}

_calls: dict[str, list[float]] = defaultdict(list)


def _check(bucket: str) -> None:
    limit, window = _LIMITS[bucket]
    now = time.monotonic()
    recent = [t for t in _calls[bucket] if now - t < window]
    _calls[bucket] = recent

    if len(recent) >= limit:
        oldest = min(recent)
        retry_in = int(window - (now - oldest)) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"That is {limit} of these in the last hour, which is almost certainly a "
                f"loop rather than you. Try again in about {retry_in // 60 + 1} minutes."
            ),
            headers={"Retry-After": str(retry_in)},
        )
    _calls[bucket].append(now)


def limit_llm(request: Request) -> None:
    """Anything that calls a model. Used as a FastAPI dependency."""
    _check("llm")


def limit_scout_run(request: Request) -> None:
    """Anything that spends Yutori credit."""
    _check("scout_run")


def reset() -> None:
    """For tests. Nothing in the app calls this."""
    _calls.clear()
