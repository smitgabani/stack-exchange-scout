"""The LLM side of the app, made inspectable.

Everything here reads the real constants and the real prompt rather than
restating them, so the page cannot drift from what the code actually sends. A
transparency page that paraphrases is worse than no page.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.integrations.llm import CHALLENGE_SCHEMA
from app.models.challenge import Challenge
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import challenge_service, digest_service, prompt_service
from app.services.profile_service import get_or_create_profile

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config")
async def llm_config(db: AsyncSession = Depends(get_db)) -> dict:
    """Every value that shapes a challenge, read from the code that uses it."""
    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)
    template = await prompt_service.get_active(db)

    return {
        "provider": profile_data.llm.provider,
        "prompt": {
            "version": template.version,
            "is_default": template.version == 0,
            # Shown apart so the page can make clear which half is editable.
            "system_instruction": template.system_instruction,
            "safety_clause": challenge_service.SAFETY_CLAUSE,
            "composed_system_instruction": challenge_service.compose_system_instruction(
                template.system_instruction
            ),
            "user_preamble": template.user_preamble,
            "default_system_instruction": challenge_service.DEFAULT_SYSTEM_GUIDANCE,
            "default_user_preamble": challenge_service.DEFAULT_USER_PREAMBLE,
        },
        "limits": {
            "max_body_chars": challenge_service.MAX_BODY_CHARS,
            "attempts": 2,
            "hint_labels": list(challenge_service.HINT_LABELS),
            "max_prompt_chars": prompt_service.MAX_PROMPT_CHARS,
        },
        "schema": CHALLENGE_SCHEMA,
        "validation": {
            # Surfaced as patterns rather than prose: the page should show the
            # rule that runs, not a description of it that can fall behind.
            "solution_tells": [p.pattern for p in challenge_service._SOLUTION_TELLS],
            "code_fence": challenge_service._CODE_FENCE.pattern,
        },
        "withheld": [
            "the accepted answer",
            "any answer bodies",
            "comments",
        ],
    }


class PromptIn(BaseModel):
    system_instruction: str = Field(min_length=1)
    user_preamble: str = Field(min_length=1)
    notes: str | None = None


@router.get("/prompts")
async def list_prompts(db: AsyncSession = Depends(get_db)) -> dict:
    rows = await prompt_service.list_versions(db)
    return {
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "system_instruction": row.system_instruction,
                "user_preamble": row.user_preamble,
                "notes": row.notes,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post("/prompts", status_code=status.HTTP_201_CREATED)
async def save_prompt(body: PromptIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Store a new prompt version and make it active.

    Never edits a row in place — `challenges.prompt_version` has to keep
    pointing at the text that produced each batch.
    """
    try:
        row = await prompt_service.save_version(
            db,
            system_instruction=body.system_instruction,
            user_preamble=body.user_preamble,
            notes=body.notes,
        )
    except prompt_service.PromptError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"version": row.version, "is_active": row.is_active}


@router.post("/prompts/{version}/activate")
async def activate_prompt(version: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await prompt_service.activate(db, version)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such prompt version")
    return {"version": row.version, "is_active": True}


@router.post("/prompts/reset")
async def reset_prompt(db: AsyncSession = Depends(get_db)) -> dict:
    """Go back to the prompt that ships in the code."""
    await prompt_service.reset_to_default(db)
    return {"version": 0, "is_default": True}


@router.get("/preview")
async def preview(
    question_id: uuid.UUID = Query(...),
    system_instruction: str | None = None,
    user_preamble: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The exact bytes that would be sent for this question. Costs nothing.

    Takes optional overrides so an unsaved edit can be previewed before it is
    stored — otherwise tuning a prompt means saving a version to find out what
    it looks like.
    """
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    template = await prompt_service.get_active(db)
    composed = challenge_service.compose_system_instruction(
        system_instruction or template.system_instruction
    )
    prompt = challenge_service.build_prompt(
        question, question.interesting_reason, user_preamble or template.user_preamble
    )

    return {
        "question": {
            "id": str(question.id),
            "title": question.title,
            "status": question.status,
            "body_chars": len(question.body or ""),
            "body_chars_sent": len(
                challenge_service.strip_html(question.body or "")[: challenge_service.MAX_BODY_CHARS]
            ),
        },
        "system_instruction": composed,
        "prompt": prompt,
        "prompt_chars": len(prompt),
    }


@router.post("/test")
async def test_generate(
    question_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run one real generation and throw the result away.

    Costs one LLM call and writes nothing — no `Challenge` row, no change to
    the question's status. The point is to see what the model actually returns,
    and whether validation accepts it, without committing to it.
    """
    question = await db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)

    try:
        provider = await digest_service.resolve_provider(db, profile_data)
    except digest_service.DigestError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    template = await prompt_service.get_active(db)
    try:
        challenge = await challenge_service.generate_challenge(
            provider, question, selection_reason="a test run", template=template
        )
    except challenge_service.ChallengeValidationError as exc:
        # A rejection is a useful result here, not an error to hide: it is how
        # a prompt that produces spoilers gets caught before it is activated.
        return {
            "ok": False,
            "provider": provider.name,
            "model": provider.model,
            "prompt_version": template.version,
            "error": str(exc),
        }

    return {
        "ok": True,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": template.version,
        "challenge": {
            "problem_summary": challenge.problem_summary,
            "why_interesting": challenge.why_interesting,
            "concepts": challenge.concepts,
            "starting_direction": challenge.starting_direction,
            "hints": challenge.hints,
            "estimated_difficulty": challenge.estimated_difficulty,
        },
    }


@router.get("/generations")
async def generations(db: AsyncSession = Depends(get_db), limit: int = 100) -> dict:
    """Every challenge with the prompt and model that made it.

    `provider`, `model` and `prompt_version` are recorded so a bad batch can be
    traced to what produced it; until now nothing surfaced them.
    """
    rows = (
        await db.execute(
            select(Challenge, Question)
            .join(Question, Question.id == Challenge.question_id)
            .order_by(Challenge.created_at.desc())
            .limit(limit)
        )
    ).all()

    return {
        "generations": [
            {
                "id": str(challenge.id),
                "question_title": question.title,
                "source": challenge.source,
                "provider": challenge.provider,
                "model": challenge.model,
                "prompt_version": challenge.prompt_version,
                "estimated_difficulty": challenge.estimated_difficulty,
                "created_at": challenge.created_at.isoformat() if challenge.created_at else None,
            }
            for challenge, question in rows
        ]
    }
