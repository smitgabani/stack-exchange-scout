import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.models.question import Question
from app.schemas.profile import ProfileData

# prd.md §15 fixes these weights; the sub-formulas below are this project's
# choice, since the PRD deliberately leaves "the exact algorithm" open.
WEIGHTS = {
    "topic_relevance": 0.30,
    "technical_depth": 0.25,
    "solve_opportunity": 0.20,
    "recency": 0.10,
    "quality": 0.10,
    "novelty": 0.05,
}

_CODE_BLOCK = re.compile(r"<pre>|<code>|```")


@dataclass
class Scores:
    topic_relevance: int
    technical_depth: int
    solve_opportunity: int
    recency: int
    quality: int
    novelty: int

    @property
    def total(self) -> float:
        weighted = (
            self.topic_relevance * WEIGHTS["topic_relevance"]
            + self.technical_depth * WEIGHTS["technical_depth"]
            + self.solve_opportunity * WEIGHTS["solve_opportunity"]
            + self.recency * WEIGHTS["recency"]
            + self.quality * WEIGHTS["quality"]
            + self.novelty * WEIGHTS["novelty"]
        )
        return round(weighted, 2)


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _has_code(body: str) -> bool:
    return bool(_CODE_BLOCK.search(body))


def score_topic_relevance(question: Question, profile: ProfileData) -> int:
    """Weight of the best-matching topic, bonused for breadth, penalised for
    anything the user explicitly avoids.

    Returns 0 when nothing matches, which is what keeps genuinely off-topic
    questions out of the digest no matter how good they look otherwise.
    """
    if not profile.topics:
        return 50  # nothing configured yet — neutral rather than zero

    tags = {tag.lower() for tag in (question.tags or [])}
    title = (question.title or "").lower()
    haystack = f"{title} {' '.join(tags)} {(question.body or '')[:2000].lower()}"

    matched = [t for t in profile.topics if t.name.lower() in tags or t.name.lower() in title]
    if not matched:
        return 0

    value = max(t.weight for t in matched)
    value += min(15, 5 * (len(matched) - 1))
    if any(c.lower() in haystack for c in profile.preferred_concepts):
        value += 10
    if any(c.lower() in haystack for c in profile.excluded_concepts):
        value -= 40
    return _clamp(value)


def score_technical_depth(question: Question, profile: ProfileData) -> int:
    """Yutori's difficulty estimate, adjusted for substance and for how far it
    sits outside the user's requested difficulty window.
    """
    difficulty = question.difficulty or 3
    body = question.body or ""

    value = (difficulty - 1) * 25
    if _has_code(body):
        value += 10
    value += min(10, len(body) / 200)

    if difficulty < profile.difficulty.minimum:
        value -= 25 * (profile.difficulty.minimum - difficulty)
    elif difficulty > profile.difficulty.maximum:
        value -= 10 * (difficulty - profile.difficulty.maximum)
    return _clamp(value)


def score_solve_opportunity(question: Question, profile: ProfileData) -> int:
    """How much room is left for the user to actually solve it themselves."""
    answers = question.answer_count or 0

    if question.accepted_answer_id is not None:
        value = 30.0  # already solved for them — the point is largely gone
    else:
        value = max(20.0, 100 - 20 * answers)

    if answers > profile.question_preferences.max_answers:
        return 0

    if len((question.body or "").strip()) < 200:
        value = min(value, 40)
    return _clamp(value)


def score_recency(question: Question, profile: ProfileData, now: datetime) -> int:
    """Half-life decay. Falls back to last activity when the user cares less
    about raw age, so a long-running thread still reads as live.
    """
    if profile.question_preferences.prefer_recent:
        reference, half_life_days = question.question_created_at, 30
    else:
        reference, half_life_days = question.last_activity_at, 90

    reference = reference or question.question_created_at
    if reference is None:
        return 50  # unknown age — neither rewarded nor punished

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    age_days = max(0.0, (now - reference).total_seconds() / 86400)
    return _clamp(100 * (0.5 ** (age_days / half_life_days)))


def score_quality(question: Question) -> int:
    """Community signal plus basic signs of a well-formed question."""
    votes = max(0, question.score or 0)
    body = question.body or ""
    title = question.title or ""

    value = min(60.0, 20 * math.log2(1 + votes))
    if _has_code(body):
        value += 20
    if 300 <= len(body) <= 6000:
        value += 10
    if 20 <= len(title) <= 150:
        value += 10
    return _clamp(value)


def score_novelty(question: Question, recent_tags: Counter[str]) -> int:
    """Penalises tags the user has just been shown, so a digest doesn't become
    five variations of the same topic.
    """
    if not recent_tags:
        return 100
    overlap = sum(1 for tag in (question.tags or []) if recent_tags.get(tag.lower()))
    return _clamp(100 - 25 * overlap)


def is_digest_eligible(question: Question) -> bool:
    """The quality-over-quantity guard (prd.md §15, M6-B3).

    Three independent bars, because each catches a failure the weighted total
    hides. The total rejects weak candidates. The topic floor rejects
    questions that are excellent but not about anything the user asked for.
    The solve-opportunity floor rejects questions that are already thoroughly
    answered — scoring real Stack Overflow data showed a 2008 question with 51
    answers and an accepted one clearing the total on topic, depth and quality
    alone, which is exactly the thing this product exists not to send.

    A digest of four is the correct outcome when only four qualify —
    thresholds are never lowered to reach the target count (prd.md §26).
    """
    if question.candidate_score is None:
        return False
    if float(question.candidate_score) < settings.digest_min_score:
        return False
    if (question.topic_relevance or 0) < settings.digest_min_topic_relevance:
        return False
    return (question.solve_opportunity or 0) >= settings.digest_min_solve_opportunity


def score(
    question: Question,
    profile: ProfileData,
    *,
    recent_tags: Counter[str] | None = None,
    now: datetime | None = None,
) -> Scores:
    """Score one question, deterministically.

    Pure by design (tdd.md §4.6): no database, no clock of its own, no network.
    The caller supplies `now` and the recent-tag history, which is what makes
    every sub-score independently unit-testable.
    """
    now = now or datetime.now(UTC)
    recent_tags = recent_tags if recent_tags is not None else Counter()

    return Scores(
        topic_relevance=score_topic_relevance(question, profile),
        technical_depth=score_technical_depth(question, profile),
        solve_opportunity=score_solve_opportunity(question, profile),
        recency=score_recency(question, profile, now),
        quality=score_quality(question),
        novelty=score_novelty(question, recent_tags),
    )
