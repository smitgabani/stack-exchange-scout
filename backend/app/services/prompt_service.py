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
from functools import partial

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_template import PromptTemplate
from app.services import challenge_service, versioned

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


list_versions = partial(versioned.list_versions, model=PromptTemplate)
activate = partial(versioned.activate, model=PromptTemplate)
reset_to_default = partial(versioned.reset, model=PromptTemplate)


async def save_version(
    db: AsyncSession, *, system_instruction: str, user_preamble: str, notes: str | None = None
) -> PromptTemplate:
    """Store a new version and make it active."""
    system_instruction, user_preamble = _validate(system_instruction, user_preamble)
    row = await versioned.save_active(
        db,
        PromptTemplate(system_instruction=system_instruction, user_preamble=user_preamble, notes=notes),
        floor=challenge_service.PROMPT_VERSION,
    )
    logger.info("Prompt template v%d activated", row.version)
    return row
