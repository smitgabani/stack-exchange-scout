import html
import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.models.challenge import Challenge
from app.models.question import Question

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
# Resend's shared sender works without DNS setup, which is enough for a
# single-recipient personal tool.
DEFAULT_FROM = "Challenge Scout <onboarding@resend.dev>"

EMPTY_DIGEST_BODY = (
    "No great challenges were found this cycle. "
    "Your next challenge will arrive in {days} days."
)


class EmailError(RuntimeError):
    pass


def _escape(value: str | None) -> str:
    """Everything interpolated into the email traces back to Stack Overflow or
    an LLM, so all of it is escaped before it becomes HTML.
    """
    return html.escape(value or "", quote=True)


def render_empty_digest(frequency_days: int) -> tuple[str, str]:
    subject = f"Your Stack Overflow Challenges — {datetime.now(UTC).strftime('%B %-d')}"
    body = EMPTY_DIGEST_BODY.format(days=frequency_days)
    return subject, f"<html><body><p>{_escape(body)}</p></body></html>"


def render_digest(pairs: list[tuple[Question, Challenge]], *, app_base_url: str = "") -> tuple[str, str]:
    """Render the digest email (prd.md §21).

    Hints sit inside <details> so the email can be read without spoiling the
    very thing it exists to preserve (prd.md §18).
    """
    subject = f"Your Stack Overflow Challenges — {datetime.now(UTC).strftime('%B %-d')}"
    count = len(pairs)

    sections: list[str] = [
        "<h1 style=\"font-weight:500\">Your Stack Overflow Challenges</h1>",
        f"<p>{count} question{'s' if count != 1 else ''} selected for you.</p>",
    ]

    for index, (question, challenge) in enumerate(pairs, start=1):
        tags = ", ".join(question.tags or [])
        difficulty = challenge.estimated_difficulty or question.difficulty or "?"
        challenge_url = f"{app_base_url.rstrip('/')}/challenge/{challenge.id}" if app_base_url else ""

        hints_html = "".join(
            f"<details><summary>{_escape(hint.get('label'))}</summary>"
            f"<p>{_escape(hint.get('text'))}</p></details>"
            for hint in (challenge.hints or [])
        )

        sections.append(
            f"""
<hr />
<h2 style="font-weight:500">#{index} {_escape(question.title)}</h2>
<p><strong>Difficulty:</strong> {difficulty}/5<br />
<strong>Tags:</strong> {_escape(tags)}</p>

<h3 style="font-weight:500">Problem</h3>
<p>{_escape(challenge.problem_summary)}</p>

<h3 style="font-weight:500">Why it's interesting</h3>
<p>{_escape(challenge.why_interesting)}</p>

<h3 style="font-weight:500">Start here</h3>
<p>{_escape(challenge.starting_direction)}</p>

{hints_html}

<p><a href="{_escape(question.url)}">Open Question</a>
{f' &middot; <a href="{_escape(challenge_url)}">View challenge</a>' if challenge_url else ''}</p>
"""
        )

    return subject, f"<html><body style=\"font-family:Arial,sans-serif;line-height:1.5\">{''.join(sections)}</body></html>"


async def send_email(*, subject: str, html_body: str, to: str | None = None) -> str:
    """Send one email through Resend, returning its message id."""
    recipient = to or settings.digest_recipient_email
    if not recipient:
        raise EmailError("DIGEST_RECIPIENT_EMAIL is not configured")
    if not settings.resend_api_key:
        raise EmailError("RESEND_API_KEY is not configured")

    payload = {
        "from": settings.email_from or DEFAULT_FROM,
        "to": [recipient],
        "subject": subject,
        "html": html_body,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
    except httpx.HTTPError as exc:
        raise EmailError(f"Resend request failed: {exc}") from exc

    if response.status_code >= 400:
        raise EmailError(f"Resend returned {response.status_code}: {response.text[:300]}")

    return str(response.json().get("id", ""))
