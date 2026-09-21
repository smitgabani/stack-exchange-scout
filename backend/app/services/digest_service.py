import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.gemini import GeminiProvider
from app.integrations.llm import LLMError, LLMProvider
from app.integrations.openai import OpenAIProvider
from app.models.challenge import Challenge as ChallengeRow
from app.models.digest import Digest, DigestQuestion
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import (
    challenge_blocks,
    challenge_service,
    format_service,
    prompt_service,
    ranking_service,
)
from app.services.credentials_service import get_api_key

logger = logging.getLogger(__name__)


class DigestError(RuntimeError):
    pass


async def resolve_provider(db: AsyncSession, profile_data: ProfileData) -> LLMProvider:
    """Build the provider the profile selects (prd.md §7.3)."""
    if profile_data.llm.provider == "openai":
        key = await get_api_key(db, "openai_api_key")
        if key is None:
            raise DigestError("No usable OpenAI key stored")
        return OpenAIProvider(key)

    key = await get_api_key(db, "gemini_api_key")
    if key is None:
        raise DigestError("No usable Gemini key stored — re-enter it in Settings")
    return GeminiProvider(key)


async def select_candidates(db: AsyncSession, profile_data: ProfileData) -> list[Question]:
    """Pick the top N eligible candidates.

    Applies the quality guard *before* taking the top N, so a thin pool yields
    a short digest rather than a padded one — prd.md §26 forbids lowering the
    bar to reach the target count.
    """
    candidates = (
        await db.scalars(
            select(Question)
            .where(Question.status == "candidate", Question.candidate_score.is_not(None))
            .order_by(Question.candidate_score.desc())
            .limit(200)
        )
    ).all()

    eligible = [q for q in candidates if ranking_service.is_digest_eligible(q)]
    return eligible[: profile_data.digest.questions]


async def generate(
    db: AsyncSession,
    profile_data: ProfileData,
    profile_version: int,
    *,
    provider: LLMProvider | None = None,
) -> Digest:
    """Build a digest: select, curate, persist (prd.md §25 `digest_generate`).

    Generation and sending are separate steps, so a digest can be inspected
    before it goes out.
    """
    selected = await select_candidates(db, profile_data)

    digest = Digest(status="generating", profile_version=profile_version, question_count=len(selected))
    db.add(digest)
    await db.commit()
    await db.refresh(digest)

    if not selected:
        # Not a failure — "nothing met the bar" is a legitimate outcome with
        # its own email (prd.md §26).
        digest.status = "empty"
        await db.commit()
        await db.refresh(digest)
        return digest

    provider = provider or await resolve_provider(db, profile_data)
    # Resolved once, not per question: a digest whose challenges were made by
    # two different prompts would be untraceable.
    template = await prompt_service.get_active(db)
    # One format for the whole digest, for the same reason as the prompt: a
    # digest whose challenges have different shapes is not one digest.
    fmt = await format_service.get_default(db)

    try:
        for position, question in enumerate(selected):
            challenge = await challenge_service.generate_challenge(
                provider,
                question,
                selection_reason=question.interesting_reason,
                template=template,
                blocks=fmt.blocks,
            )
            await format_service.verify_content_links(challenge.content, fmt.blocks)
            db.add(
                ChallengeRow(
                    digest_id=digest.id,
                    question_id=question.id,
                    problem_summary=challenge.problem_summary,
                    why_interesting=challenge.why_interesting,
                    concepts=challenge.concepts,
                    starting_direction=challenge.starting_direction,
                    hints=challenge.hints,
                    estimated_difficulty=challenge.estimated_difficulty,
                    provider=provider.name,
                    model=provider.model,
                    prompt_version=template.version or challenge_service.PROMPT_VERSION,
                    content=challenge.content,
                    format_name=fmt.name,
                    generations=[
                        challenge_service.generation_record(
                            system_instruction=challenge.composed_instruction,
                            blocks=fmt.blocks,
                            prompt_version=template.version
                            or challenge_service.PROMPT_VERSION,
                            provider=provider.name,
                            model=provider.model,
                        )
                    ],
                )
            )
            db.add(DigestQuestion(digest_id=digest.id, question_id=question.id, position=position))
            question.status = "selected"
    except Exception as exc:
        # Never send a partially generated digest (prd.md §26) — mark it failed
        # and leave it for a retry rather than emailing half a digest.
        logger.error("Digest %s generation failed: %s", digest.id, exc)
        digest.status = "generation_failed"
        await db.commit()
        raise DigestError(f"Digest generation failed: {exc}") from exc

    digest.status = "generated"
    await db.commit()
    await db.refresh(digest)
    return digest


class PromotionError(RuntimeError):
    """A question cannot be turned into a challenge on demand."""


async def promote_question(
    db: AsyncSession,
    profile_data: ProfileData,
    question: Question,
    *,
    provider: LLMProvider | None = None,
    format_id: int | None = None,
) -> ChallengeRow:
    """Curate one question into a challenge outside any digest.

    The counterpart to `generate`: same curator, same prompt, same validation,
    but the caller chose the question instead of the scoring formula. That
    matters because the formula is a proxy for interest, not interest itself —
    a question it passed over can still be the one worth solving.

    Costs one LLM call. Unlike a discovery run it spends no Yutori credit, so
    it is cheap enough to sit behind an ordinary button.
    """
    if question.status == "enrichment_pending":
        raise PromotionError(
            "This question has not been enriched yet, so there is no content to build a "
            "challenge from. Run Enrich pending first."
        )
    if not (question.body or question.title):
        raise PromotionError("This question has no title or body to build a challenge from.")

    existing = await db.scalar(
        select(ChallengeRow).where(
            ChallengeRow.question_id == question.id, ChallengeRow.digest_id.is_(None)
        )
    )
    if existing is not None:
        raise PromotionError("This question already has a challenge.")

    provider = provider or await resolve_provider(db, profile_data)

    template = await prompt_service.get_active(db)
    try:
        fmt = await format_service.resolve_for_run(db, format_id)
    except format_service.FormatError as exc:
        raise PromotionError(str(exc)) from exc

    try:
        challenge = await challenge_service.generate_challenge(
            provider,
            question,
            selection_reason="you picked this question yourself",
            template=template,
            blocks=fmt.blocks,
        )
    except Exception as exc:
        raise PromotionError(f"Challenge generation failed: {exc}") from exc

    # Dead links are dropped before the challenge is stored: a page full of
    # 404s undermines confidence in everything else on it.
    await format_service.verify_content_links(challenge.content, fmt.blocks)

    row = ChallengeRow(
        digest_id=None,
        question_id=question.id,
        problem_summary=challenge.problem_summary,
        why_interesting=challenge.why_interesting,
        concepts=challenge.concepts,
        starting_direction=challenge.starting_direction,
        hints=challenge.hints,
        estimated_difficulty=challenge.estimated_difficulty,
        provider=provider.name,
        model=provider.model,
        prompt_version=template.version or challenge_service.PROMPT_VERSION,
        content=challenge.content,
        format_name=fmt.name,
        generations=[
            challenge_service.generation_record(
                system_instruction=challenge.composed_instruction,
                blocks=fmt.blocks,
                prompt_version=template.version or challenge_service.PROMPT_VERSION,
                provider=provider.name,
                model=provider.model,
            )
        ],
    )
    db.add(row)

    # `select_candidates` only ever looks at rows still marked `candidate`, so
    # this is what stops the next digest curating a second challenge for a
    # question that already has one.
    if question.status == "candidate":
        question.status = "selected"

    await db.commit()
    await db.refresh(row)
    return row


def content_for(challenge: ChallengeRow) -> dict:
    """A challenge's blocks, materialised for ones made before formats existed.

    Those rows have `content` null and their six fields only in columns, so
    without this a top-up would think every core block was missing and ask the
    model to produce them all again.
    """
    if challenge.content:
        return dict(challenge.content)
    return {
        "problem_summary": challenge.problem_summary,
        "why_interesting": challenge.why_interesting,
        "concepts": challenge.concepts or [],
        "starting_direction": challenge.starting_direction,
        "hints": challenge.hints or [],
        **(
            {"estimated_difficulty": challenge.estimated_difficulty}
            if challenge.estimated_difficulty is not None
            else {}
        ),
    }


async def reformat_challenge(
    db: AsyncSession,
    profile_data: ProfileData,
    challenge: ChallengeRow,
    question: Question,
    *,
    format_id: int | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Add the blocks a format wants that this challenge does not have yet.

    A top-up rather than a regeneration. Blocks already present are left
    exactly as they are, so hints you have already revealed do not change
    under you mid-solve, and the challenge keeps its id — which is what keeps
    the link in an already-sent digest working.

    Costs one LLM call, and none at all when there is nothing to add.
    """
    try:
        fmt = await format_service.resolve_for_run(db, format_id)
    except format_service.FormatError as exc:
        raise PromotionError(str(exc)) from exc

    current = content_for(challenge)
    missing = [block for block in fmt.blocks if block.key not in current]

    if not missing:
        # Still record the format: the challenge now satisfies it, and saying
        # so is cheaper and truer than pretending nothing happened.
        challenge.format_name = fmt.name
        await db.commit()
        return {
            "added": [],
            "missing": [],
            "dropped_links": [],
            "format": fmt.name,
            "spent_call": False,
        }

    provider = provider or await resolve_provider(db, profile_data)
    template = await prompt_service.get_active(db)

    prompt = challenge_service.build_prompt(
        question, question.interesting_reason, challenge_service.TOP_UP_PREAMBLE
    )
    system_instruction = challenge_service.compose_system_instruction(
        template.system_instruction, missing
    )
    # Every missing block is required: the schema contains exactly what was
    # asked for and did not arrive.
    schema = challenge_blocks.build_schema(missing)

    try:
        payload = await provider.generate_json(
            system_instruction=system_instruction, prompt=prompt, schema=schema
        )
        added = challenge_service.validate_partial(payload, missing)
    except (challenge_service.ChallengeValidationError, LLMError) as exc:
        raise PromotionError(f"Could not add those sections: {exc}") from exc

    dropped = await format_service.verify_content_links(added, missing)
    # A resource block whose every link failed verification is now empty, and
    # an empty block is not worth storing — but it must be reported, or it is
    # indistinguishable from one that was never requested.
    added = {key: value for key, value in added.items() if value not in (None, "", [], {})}

    challenge.content = {**current, **added}
    challenge.format_name = fmt.name
    challenge.provider = provider.name
    challenge.model = provider.model
    # Appended, not replaced: this call produced only the blocks it was asked
    # for, and the instruction that made the rest of the challenge is still
    # the truth about the rest of the challenge.
    challenge.generations = [
        *(challenge.generations or []),
        challenge_service.generation_record(
            system_instruction=system_instruction,
            blocks=missing,
            prompt_version=template.version or challenge_service.PROMPT_VERSION,
            provider=provider.name,
            model=provider.model,
        ),
    ]
    await db.commit()
    await db.refresh(challenge)

    still_missing = [block.key for block in missing if block.key not in added]
    return {
        "added": list(added.keys()),
        # Asked for and not produced. Surfaced so "I chose nine and got two"
        # is visible rather than something to work out from the page.
        "missing": still_missing,
        "dropped_links": dropped,
        "format": fmt.name,
        "spent_call": True,
    }


async def load_digest_questions(db: AsyncSession, digest_id) -> list[tuple[Question, ChallengeRow]]:
    """Questions and their challenges, in the order the digest defines."""
    rows = (
        await db.execute(
            select(Question, ChallengeRow, DigestQuestion.position)
            .join(DigestQuestion, DigestQuestion.question_id == Question.id)
            .join(
                ChallengeRow,
                (ChallengeRow.question_id == Question.id) & (ChallengeRow.digest_id == digest_id),
            )
            .where(DigestQuestion.digest_id == digest_id)
            .order_by(DigestQuestion.position)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def mark_sent(db: AsyncSession, digest: Digest) -> None:
    """Flip the digest and exactly its own questions to sent/presented."""
    pairs = await load_digest_questions(db, digest.id)
    for question, _challenge in pairs:
        question.status = "presented"
        question.last_seen_at = datetime.now(UTC)

    digest.status = "sent"
    digest.sent_at = datetime.now(UTC)
    digest.email_error = None
    await db.commit()
