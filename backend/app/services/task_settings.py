"""Turning a scout's settings into the exact request Yutori receives (M13).

Pure functions — no database, no network — so the preview a user sees and the
body `run_definition` sends come from the same code, and tests can pin both.
"""

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.integrations.yutori import CANDIDATE_OUTPUT_SCHEMA, MIN_OUTPUT_INTERVAL_SECONDS

# Yutori's own default when no timezone is sent. A start time given as wall
# clock time is read in this zone unless the scout names another.
YUTORI_DEFAULT_TIMEZONE = "America/Los_Angeles"

MONTH_SECONDS = 30 * 24 * 3600


def built_in_defaults() -> dict[str, Any]:
    """What a scout sends when nothing has been changed — today's behaviour.

    A function rather than a constant so the interval follows
    `settings.scout_run_interval_seconds`.
    """
    return {
        "output_interval_seconds": settings.scout_run_interval_seconds,
        "start": "now",
        "start_at": None,
        "user_timezone": None,
        "user_location": None,
        # Yutori defaults this to true; public reports are readable by anyone
        # holding the Scout's id, and the query carries the user's interests.
        "is_public": False,
        # The app sends its own digest; Yutori's email would duplicate it.
        "email_from_yutori": False,
        "subscribers": [],
        "output_schema": CANDIDATE_OUTPUT_SCHEMA,
    }


def effective(defaults: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults with a scout's overrides laid over them. Unset never overrides."""
    merged = dict(defaults)
    for key, value in (overrides or {}).items():
        if value is not None and key in merged:
            merged[key] = value
    return merged


def start_timestamp(eff: dict[str, Any]) -> int | None:
    """The Unix time a Scout should start, or None to start now."""
    if eff.get("start") != "at" or not eff.get("start_at"):
        return None
    zone = ZoneInfo(eff.get("user_timezone") or YUTORI_DEFAULT_TIMEZONE)
    local = datetime.fromisoformat(eff["start_at"]).replace(tzinfo=zone)
    return int(local.timestamp())


def build_payload(
    kind: str, query: str, eff: dict[str, Any], webhook_url: str | None
) -> dict[str, Any]:
    """The request body for creating a research task or a Scout.

    Only fields that are set are included, because Yutori treats an absent
    field as "use your default" and an explicit null as something else.
    Research tasks take no interval, start time or visibility — they run once
    and are never public.
    """
    payload: dict[str, Any] = {
        "query": query,
        "output_schema": eff.get("output_schema") or CANDIDATE_OUTPUT_SCHEMA,
        "skip_email": not eff.get("email_from_yutori", False),
    }
    if eff.get("user_timezone"):
        payload["user_timezone"] = eff["user_timezone"]
    if eff.get("user_location"):
        payload["user_location"] = eff["user_location"]
    if webhook_url:
        payload["webhook_url"] = webhook_url
        payload["webhook_format"] = "scout"
    if kind == "scout":
        payload["output_interval"] = max(
            int(eff.get("output_interval_seconds") or settings.scout_run_interval_seconds),
            MIN_OUTPUT_INTERVAL_SECONDS,
        )
        payload["is_public"] = bool(eff.get("is_public", False))
        start = start_timestamp(eff)
        if start is not None:
            payload["start_timestamp"] = start
    return payload


def monthly_cost(interval_seconds: int | None) -> float:
    """What a Scout at this interval costs over a 30-day month."""
    if not interval_seconds or interval_seconds <= 0:
        return 0.0
    return round(MONTH_SECONDS / interval_seconds * settings.yutori_run_cost_usd, 2)


def mask_webhook_url(url: str | None) -> str | None:
    """Strip the query string from a webhook URL before it leaves the backend.

    Yutori echoes back the `webhook_url` we registered, and ours carries
    YUTORI_WEBHOOK_SECRET as a query parameter — that secret is the only thing
    authenticating inbound candidate data, so it must never reach the browser.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme:
        return "(configured)"
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def mask(payload: dict[str, Any]) -> dict[str, Any]:
    """A payload safe to show or store: the webhook secret replaced."""
    safe = dict(payload)
    if safe.get("webhook_url"):
        safe["webhook_url"] = f"{mask_webhook_url(safe['webhook_url'])}?token=••••"
    return safe
