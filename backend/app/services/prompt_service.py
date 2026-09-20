"""Versioned, editable prompt guidance for the challenge curator.

Only the guidance is stored. The prompt-injection defences — the untrusted-data
clause and the `<QUESTION>` fence — are composed in `challenge_service` around
whatever is active here, so no edit can remove them. That is the whole security
posture of this feature: the blast radius of a bad prompt is poor challenges,
never an unfenced model call.

Templates are immutable. A save writes a new version and activates it, which
keeps `challenges.prompt_version` pointing at the exact text that produced a
given batch, and makes rollback a matter of reactivating an old row.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_template import PromptTemplate
from app.services import challenge_service

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 8000


class PromptError(RuntimeError):
    """A prompt was rejected before it could be stored."""


def _validate(system_instruction: str, user_preamble: str) -> tuple[str, str]:
    """Reject prompts that are empty, oversized, or try to re-fence the input.

    Length is capped because the prompt is sent on every generation and a
    runaway paste is paid for on each one. The fence check is not a security
    boundary — the real defence is that the fence is added in code — but a
    template carrying its own `<QUESTION>` block would produce two, and the
    model would see a confused, nested structure.
    """
    system_instruction = (system_instruction or "").strip()
    user_preamble = (user_preamble or "").strip()

    if not system_instruction:
        raise PromptError("The system instruction cannot be empty.")
    if not user_preamble:
        raise PromptError("The preamble cannot be empty.")
    if len(system_instruction) + len(user_preamble) > MAX_PROMPT_CHARS:
        raise PromptError(
            f"The prompt is too long — keep it under {MAX_PROMPT_CHARS} characters combined."
        )
    for text in (system_instruction, user_preamble):
        if "<QUESTION>" in text.upper():
            raise PromptError(
                "Do not include a <QUESTION> block — the application adds it, along with the "
                "instruction that its contents are untrusted data."
            )
    return system_instruction, user_preamble


async def get_active(db: AsyncSession) -> challenge_service.PromptText:
    """The prompt in force, falling back to the code defaults.

    Falling back rather than seeding on first use keeps a fresh install and an
    install whose templates were all deleted behaving identically, and means
    challenge generation never depends on this table existing.
    """
    row = await db.scalar(select(PromptTemplate).where(PromptTemplate.is_active))
    if row is None:
        return challenge_service.PromptText(
            system_instruction=challenge_service.DEFAULT_SYSTEM_GUIDANCE,
            user_preamble=challenge_service.DEFAULT_USER_PREAMBLE,
            version=0,
        )
    return challenge_service.PromptText(
        system_instruction=row.system_instruction,
        user_preamble=row.user_preamble,
        version=row.version,
    )


async def list_versions(db: AsyncSession) -> list[PromptTemplate]:
    return list(
        await db.scalars(select(PromptTemplate).order_by(PromptTemplate.version.desc()))
    )


async def save_version(
    db: AsyncSession, *, system_instruction: str, user_preamble: str, notes: str | None = None
) -> PromptTemplate:
    """Store a new version and make it active."""
    system_instruction, user_preamble = _validate(system_instruction, user_preamble)

    highest = await db.scalar(select(PromptTemplate.version).order_by(PromptTemplate.version.desc()))
    # Version 1 is the code default, so a first stored edit starts at 2 and
    # never collides with the provenance already on existing challenges.
    next_version = max(highest or 0, challenge_service.PROMPT_VERSION) + 1

    await db.execute(update(PromptTemplate).values(is_active=False).where(PromptTemplate.is_active))
    row = PromptTemplate(
        version=next_version,
        system_instruction=system_instruction,
        user_preamble=user_preamble,
        notes=notes,
        is_active=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    logger.info("Prompt template v%d activated", row.version)
    return row


async def activate(db: AsyncSession, version: int) -> PromptTemplate | None:
    """Roll back to a stored version without copying it forward."""
    row = await db.scalar(select(PromptTemplate).where(PromptTemplate.version == version))
    if row is None:
        return None
    await db.execute(update(PromptTemplate).values(is_active=False).where(PromptTemplate.is_active))
    row.is_active = True
    await db.commit()
    await db.refresh(row)
    return row


async def reset_to_default(db: AsyncSession) -> None:
    """Deactivate every stored template, returning to the prompt in the code."""
    await db.execute(update(PromptTemplate).values(is_active=False).where(PromptTemplate.is_active))
    await db.commit()
