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
from app.models.challenge import Challenge
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import (
    block_service,
    challenge_blocks,
    challenge_service,
    digest_service,
    format_service,
    prompt_service,
)
from app.services.profile_service import get_or_create_profile

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config")
async def llm_config(db: AsyncSession = Depends(get_db)) -> dict:
    """Every value that shapes a challenge, read from the code that uses it."""
    profile = await get_or_create_profile(db)
    profile_data = ProfileData.model_validate(profile.data)
    template = await prompt_service.get_active(db)
    fmt = await format_service.get_default(db)

    return {
        "provider": profile_data.llm.provider,
        "prompt": {
            "version": template.version,
            "is_default": template.version == 0,
            # Shown apart so the page can make clear which half is editable.
            "system_instruction": template.system_instruction,
            "safety_clause": challenge_service.SAFETY_CLAUSE,
            "composed_system_instruction": challenge_service.compose_system_instruction(
                template.system_instruction, fmt.blocks
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
        "format": {"name": fmt.name, "blocks": fmt.keys},
        "schema": challenge_blocks.build_schema(fmt.blocks),
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
    format_id: int | None = None,
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
    try:
        fmt = await format_service.resolve_for_run(db, format_id)
    except format_service.FormatError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    composed = challenge_service.compose_system_instruction(
        system_instruction or template.system_instruction, fmt.blocks
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
        "format": {"name": fmt.name, "blocks": fmt.keys},
        "schema": challenge_blocks.build_schema(fmt.blocks),
        "system_instruction": composed,
        "prompt": prompt,
        "prompt_chars": len(prompt),
    }


@router.post("/test")
async def test_generate(
    question_id: uuid.UUID = Query(...),
    format_id: int | None = None,
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
        fmt = await format_service.resolve_for_run(db, format_id)
    except format_service.FormatError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        challenge = await challenge_service.generate_challenge(
            provider,
            question,
            selection_reason="a test run",
            template=template,
            blocks=fmt.blocks,
        )
    except challenge_service.ChallengeValidationError as exc:
        # A rejection is a useful result here, not an error to hide: it is how
        # a prompt that produces spoilers gets caught before it is activated.
        return {
            "ok": False,
            "provider": provider.name,
            "model": provider.model,
            "prompt_version": template.version,
            "format": {"name": fmt.name, "blocks": fmt.keys},
            "error": str(exc),
        }

    # Links are checked here too, so a test shows the same resources a real
    # generation would keep rather than a rosier list.
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
                "format_name": challenge.format_name,
                # What was actually sent, per call. Block instructions are
                # editable, so recomposing this at read time would show the
                # current wording and misattribute what this was made from.
                # Null on anything generated before that was recorded.
                "generations": challenge.generations,
            }
            for challenge, question in rows
        ]
    }


# --- challenge formats ---------------------------------------------------


@router.get("/blocks")
async def blocks(db: AsyncSession = Depends(get_db)) -> dict:
    """The block library a format is built from — both halves of it.

    Served from the registry and the database rather than restated here, so a
    block added in code appears in the editor without a second edit, and one
    the user defined appears without a deploy.

    `kinds` is every renderer that exists; `custom_kinds` is the subset a
    user-defined block may choose. They differ because `progressive_hints` and
    `rating` are special-cased elsewhere (ADR 0005).
    """
    return {
        "blocks": await block_service.catalogue(db),
        "kinds": list(challenge_blocks.KINDS),
        "custom_kinds": list(challenge_blocks.CUSTOM_KINDS),
        "max_instruction_chars": block_service.MAX_INSTRUCTION_CHARS,
    }


class LibraryBlockIn(BaseModel):
    key: str = Field(min_length=3, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    kind: str
    instruction: str = Field(min_length=1)
    description: str | None = None
    gated: bool = False


class LibraryBlockEdit(BaseModel):
    """The key is absent on purpose — see `block_service.update_custom`."""

    label: str = Field(min_length=1, max_length=60)
    kind: str
    instruction: str = Field(min_length=1)
    description: str | None = None
    gated: bool = False


def _custom_out(row) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "label": row.label,
        "description": row.description,
        "kind": row.kind,
        "instruction": row.instruction,
        "gated": row.gated,
        "custom": True,
        "editable": True,
    }


@router.post("/blocks/custom", status_code=status.HTTP_201_CREATED)
async def create_custom_block(body: LibraryBlockIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Define a block. Its schema comes from the kind, so none is accepted."""
    try:
        row = await block_service.create_block(
            db,
            key=body.key,
            label=body.label,
            kind=body.kind,
            instruction=body.instruction,
            description=body.description,
            gated=body.gated,
        )
    except block_service.BlockError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _custom_out(row)


@router.patch("/blocks/custom/{block_id}")
async def update_custom_block(
    block_id: int, body: LibraryBlockEdit, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        row = await block_service.update_block(
            db,
            block_id,
            label=body.label,
            kind=body.kind,
            instruction=body.instruction,
            description=body.description,
            gated=body.gated,
        )
    except block_service.BlockError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such block")
    return _custom_out(row)


@router.delete("/blocks/custom/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_block(block_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Challenges that already have this block's output keep it in `content`,
    but nothing resolves the key any more, so it stops being rendered.
    """
    if not await block_service.delete_block(db, block_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such block")


class InstructionIn(BaseModel):
    instruction: str = Field(min_length=1)


@router.put("/blocks/{block_key}/instruction")
async def set_block_instruction(
    block_key: str, body: InstructionIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Reword what a built-in block asks for. Its shape is unaffected."""
    try:
        instruction = await block_service.set_instruction(db, block_key, body.instruction)
    except block_service.BlockError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"key": block_key, "instruction": instruction, "is_overridden": True}


@router.delete("/blocks/{block_key}/instruction")
async def reset_block_instruction(block_key: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Go back to the instruction that ships in the code."""
    try:
        instruction = await block_service.reset_instruction(db, block_key)
    except block_service.BlockError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {"key": block_key, "instruction": instruction, "is_overridden": False}


class FormatIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    blocks: list[str] = Field(default_factory=list)
    description: str | None = None
    make_default: bool = False


def _format_out(row) -> dict:
    resolved = challenge_blocks.resolve(row.blocks)
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "blocks": [b.key for b in resolved],
        "optional_blocks": list(row.blocks or []),
        "is_default": row.is_default,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/formats")
async def list_formats(db: AsyncSession = Depends(get_db)) -> dict:
    rows = await format_service.list_formats(db)
    active = await format_service.get_default(db)
    return {
        "formats": [_format_out(row) for row in rows],
        # There is always an effective format, even with no rows stored.
        "active": {"name": active.name, "blocks": active.keys},
    }


@router.post("/formats", status_code=status.HTTP_201_CREATED)
async def create_format(body: FormatIn, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        row = await format_service.create(
            db,
            name=body.name,
            blocks=body.blocks,
            description=body.description,
            make_default=body.make_default,
        )
    except format_service.FormatError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _format_out(row)


@router.patch("/formats/{format_id}")
async def update_format(format_id: int, body: FormatIn, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        row = await format_service.update_format(
            db,
            format_id,
            name=body.name,
            blocks=body.blocks,
            description=body.description,
        )
    except format_service.FormatError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such format")
    return _format_out(row)


@router.post("/formats/{format_id}/default")
async def make_default(format_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await format_service.set_default(db, format_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such format")
    return _format_out(row)


@router.delete("/formats/{format_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_format(format_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Challenges made with this format are untouched — they carry its name."""
    if not await format_service.delete(db, format_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such format")
