from dataclasses import dataclass

from app.models.question import Question
from app.schemas.profile import ProfileData

# Minimum body length for a question to be considered investigable. Short
# questions are the "insufficient information" case in prd.md §14.
MIN_BODY_LENGTH = 200


@dataclass(frozen=True)
class Rejection:
    reason: str


def evaluate(question: Question, profile: ProfileData) -> Rejection | None:
    """Apply prd.md §14's auto-reject rules to an enriched question.

    Pure: no database, no clock, no I/O — the caller owns persistence. Returns
    the reason to store on the row, or None if the question survives.

    Only *hard* disqualifiers live here. §14's "penalize" list (existing
    accepted answer, many answers, age, low quality, too easy) deliberately
    does not — those shape the score in M6 rather than removing a question
    from the pool.
    """
    if question.is_closed:
        return Rejection("closed")

    if question.is_duplicate:
        return Rejection("duplicate")

    # Anything already shown to the user stays gone unless explicitly asked for
    # (prd.md §13).
    if question.status == "presented":
        return Rejection("already_presented")

    if not _matches_any_topic(question, profile):
        return Rejection("outside_topics")

    if _has_excluded_concept(question, profile):
        return Rejection("excluded_concept")

    if len((question.body or "").strip()) < MIN_BODY_LENGTH:
        return Rejection("insufficient_information")

    return None


def _searchable_text(question: Question) -> str:
    return " ".join(filter(None, [question.title or "", question.body or "", " ".join(question.tags or [])])).lower()


def _matches_any_topic(question: Question, profile: ProfileData) -> bool:
    """A question is in-scope if any profile topic shows up in its tags or title.

    With no topics configured nothing is "outside topics" — an empty profile
    shouldn't reject the entire world before the user has set anything up.
    """
    if not profile.topics:
        return True

    tags = {tag.lower() for tag in (question.tags or [])}
    title = (question.title or "").lower()

    for topic in profile.topics:
        name = topic.name.strip().lower()
        if name in tags or name in title:
            return True
    return False


def _has_excluded_concept(question: Question, profile: ProfileData) -> bool:
    if not profile.excluded_concepts:
        return False
    text = _searchable_text(question)
    return any(concept.strip().lower() in text for concept in profile.excluded_concepts)
