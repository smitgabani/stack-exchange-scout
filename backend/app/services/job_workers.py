"""The four long jobs, as background workers.

Each one does exactly what its synchronous endpoint did and returns the same
body, so the browser sees no difference beyond having to ask for it. Kept apart
from `job_service` so the machinery does not import the services it runs.

Imported for its side effects — importing it registers the workers — which is
why `main` imports it and nothing else does.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import challenge_service, digest_service, format_service, job_service
from app.services.profile_service import get_or_create_profile

logger = logging.getLogger(__name__)


async def _profile(db: AsyncSession) -> ProfileData:
    profile = await get_or_create_profile(db)
    return ProfileData.model_validate(profile.data)


@job_service.register("digest_generate")
async def generate_digest(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """The big one: N questions, each an LLM call, plus link checking."""
    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)
    digest = await digest_service.generate(db, profile_data, profile.version)
    return {
        "digest_id": str(digest.id),
        "status": digest.status,
        "question_count": digest.question_count,
    }


@job_service.register("challenge_create")
async def create_challenge(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    question_id = uuid.UUID(payload["question_id"])
    question = await db.get(Question, question_id)
    if question is None:
        raise ValueError("That question no longer exists.")

    row = await digest_service.promote_question(
        db,
        await _profile(db),
        question,
        format_id=payload.get("format_id"),
    )
    return {"challenge_id": str(row.id), "question_id": str(question_id)}


@job_service.register("reformat")
async def reformat(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    challenge_id = uuid.UUID(payload["challenge_id"])
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None:
        raise ValueError("That challenge no longer exists.")
    question = await db.get(Question, challenge.question_id)
    if question is None:
        raise ValueError("That challenge's question no longer exists.")

    return await digest_service.reformat_challenge(
        db,
        await _profile(db),
        challenge,
        question,
        format_id=payload.get("format_id"),
    )


@job_service.register("llm_test")
async def llm_test(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    """One real generation, thrown away. Writes nothing."""
    question_id = uuid.UUID(payload["question_id"])
    question = await db.get(Question, question_id)
    if question is None:
        raise ValueError("That question no longer exists.")

    profile_data = await _profile(db)
    provider = await digest_service.resolve_provider(db, profile_data)

    from app.services import prompt_service

    template = await prompt_service.get_active(db)
    fmt = await format_service.resolve_for_run(db, payload.get("format_id"))

    try:
        challenge = await challenge_service.generate_challenge(
            provider, question, selection_reason="a test run", template=template, blocks=fmt.blocks
        )
    except challenge_service.ChallengeValidationError as exc:
        # A rejection is a useful result, not a failure: it is how a prompt
        # that produces spoilers gets caught before it is activated. So the
        # job succeeds and the body says it did not.
        return {
            "ok": False,
            "provider": provider.name,
            "model": provider.model,
            "prompt_version": template.version,
            "format": {"name": fmt.name, "blocks": fmt.keys},
            "error": str(exc),
        }

    dropped = await format_service.verify_content_links(challenge.content, fmt.blocks)
    return {
        "ok": True,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": template.version,
        "format": {"name": fmt.name, "blocks": fmt.keys},
        "dropped_links": dropped,
        "content": challenge.content,
    }
