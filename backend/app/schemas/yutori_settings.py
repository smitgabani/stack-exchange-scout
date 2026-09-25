"""What a user may change about the request a scout sends to Yutori (M13).

Every field is optional: unset means "inherit the default". A scout stores
only the fields it overrides, in `scout_definitions.config["yutori"]`, so a
change to the defaults reaches every scout that hasn't said otherwise.

The webhook is deliberately absent. Its URL carries the secret that
authenticates inbound results, and Yutori delivers to exactly one URL — so
pointing it anywhere else would stop questions reaching the app at all.
"""

import json
import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# Yutori's floor on how often a Scout may run (docs.yutori.com scouts-create).
MIN_INTERVAL_SECONDS = 1800
MAX_INTERVAL_SECONDS = 365 * 24 * 3600
MAX_SUBSCRIBERS = 200  # Yutori's per-request cap on email-settings
MAX_SCHEMA_CHARS = 20_000
MAX_LOCATION_CHARS = 120

# Deliberately loose: the point is to catch typos before Yutori does, not to
# re-implement RFC 5322. Avoids adding email-validator as a dependency.
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def check_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Reject a schema the ingest step couldn't read.

    `ingest_service.parse_candidates` looks for `questions`, a list of
    objects each carrying a `url`. A schema without that shape would make
    Yutori answer in a form the app then silently throws away — paying $0.35
    for nothing.
    """
    if len(json.dumps(schema)) > MAX_SCHEMA_CHARS:
        raise ValueError(f"The output format is too large — keep it under {MAX_SCHEMA_CHARS:,} characters.")
    questions = (schema.get("properties") or {}).get("questions")
    if not isinstance(questions, dict) or questions.get("type") != "array":
        raise ValueError(
            'The output format must have a "questions" array — the app reads results from there.'
        )
    items = questions.get("items")
    if not isinstance(items, dict) or "url" not in (items.get("required") or []):
        raise ValueError(
            'Each question in the output format must require "url" — without it a result '
            "can't be turned into a question."
        )
    return schema


class YutoriSettings(BaseModel):
    """Overrides for one scout, or the app-wide defaults. Unset = inherit."""

    model_config = ConfigDict(extra="forbid")

    output_interval_seconds: int | None = Field(
        default=None, ge=MIN_INTERVAL_SECONDS, le=MAX_INTERVAL_SECONDS
    )
    # "at" pairs with start_at, a wall-clock time in the scout's timezone
    # ("2026-09-25T09:00"). Kept naive on purpose: the server converts it with
    # the effective timezone, so changing the timezone moves the start with it.
    start: Literal["now", "at"] | None = None
    start_at: str | None = None
    user_timezone: str | None = None
    user_location: str | None = Field(default=None, max_length=MAX_LOCATION_CHARS)
    is_public: bool | None = None
    email_from_yutori: bool | None = None
    subscribers: list[str] | None = Field(default=None, max_length=MAX_SUBSCRIBERS)
    output_schema: dict[str, Any] | None = None

    @field_validator("user_timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            ZoneInfo(value.strip())
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"“{value}” isn't a timezone name — use one like America/Toronto."
            ) from None
        return value.strip()

    @field_validator("user_location")
    @classmethod
    def _blank_location_is_unset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("start_at")
    @classmethod
    def _wall_clock_time(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("The start time must look like 2026-09-25T09:00.") from None
        if parsed.tzinfo is not None:
            raise ValueError("Give the start time without a timezone — the scout's timezone is used.")
        return parsed.replace(second=0, microsecond=0).isoformat(timespec="minutes")

    @field_validator("subscribers")
    @classmethod
    def _emails(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for raw in value:
            email = raw.strip().lower()
            if not _EMAIL.match(email):
                raise ValueError(f"“{raw}” isn't an email address.")
            if email not in cleaned:
                cleaned.append(email)
        return cleaned

    @field_validator("output_schema")
    @classmethod
    def _readable_schema(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return check_output_schema(value) if value is not None else None

    @model_validator(mode="after")
    def _start_at_needed(self) -> "YutoriSettings":
        if self.start == "at" and not self.start_at:
            raise ValueError("Choose a start time, or start now.")
        return self

    def overrides(self) -> dict[str, Any]:
        """Only what was set, JSON-ready — the form stored in the database."""
        return self.model_dump(mode="json", exclude_none=True)


_LABELS = {
    "output_interval_seconds": "How often",
    "start_at": "Start time",
    "user_timezone": "Timezone",
    "user_location": "Location",
    "subscribers": "Subscribers",
    "output_schema": "Output format",
}


def plain_errors(exc: ValidationError) -> str:
    """One readable sentence per problem, for a 422 the UI can show as-is."""
    messages = []
    for error in exc.errors():
        field = str(error["loc"][0]) if error.get("loc") else ""
        message = str(error["msg"]).removeprefix("Value error, ")
        if error["type"] == "greater_than_equal" and field == "output_interval_seconds":
            message = "Yutori's minimum is 30 minutes."
        if error["type"] == "extra_forbidden":
            message = "isn't a setting that can be changed."
        label = _LABELS.get(field, field.replace("_", " ").capitalize())
        messages.append(f"{label}: {message}" if label else message)
    return " ".join(messages)
