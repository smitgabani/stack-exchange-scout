import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.gemini import GeminiProvider
from app.integrations.llm import LLMProvider
from app.integrations.openai import OpenAIProvider
from app.models.challenge import Challenge as ChallengeRow
from app.models.digest import Digest, DigestQuestion
from app.models.question import Question
from app.schemas.profile import ProfileData
from app.services import challenge_service, prompt_service, ranking_service
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

    try:
        for position, question in enumerate(selected):
            challenge = await challenge_service.generate_challenge(
                provider,
                question,
                selection_reason=question.interesting_reason,
                template=template,
            )
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
        challenge = await challenge_service.generate_challenge(
            provider,
            question,
            selection_reason="you picked this question yourself",
            template=template,
        )
    except Exception as exc:
        raise PromotionError(f"Challenge generation failed: {exc}") from exc

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
