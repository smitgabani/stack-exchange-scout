from app.schemas.profile import ProfileData

# prd.md §9's template. Kept as one literal rather than assembled piecemeal so
# that what Yutori receives is readable here verbatim.
_TEMPLATE = """Monitor Stack Overflow for newly posted or recently active
questions that match my current technical interests.

Current topics:
{topics}

Preferred concepts:
{preferred_concepts}

Avoid:
{excluded_concepts}

Prefer:
- questions rated {difficulty_min}-{difficulty_max} out of 5 for difficulty
- genuine debugging or reasoning problems
- questions with enough information to investigate
- questions with few existing answers
- questions without a clearly complete accepted solution
- recent questions

Avoid:
- homework
- trivial syntax questions
- installation-only questions
- duplicates
- closed questions
- opinion-only questions

Do not solve the questions.

Return only candidate questions and structured metadata."""

_NONE = "- (none specified)"

# The built-in template, used whenever no edited version is active (M13).
DEFAULT_TEMPLATE = _TEMPLATE

# Every name a template may use. Filled from the profile in `generate`.
PLACEHOLDERS = (
    "topics",
    "preferred_concepts",
    "excluded_concepts",
    "difficulty_min",
    "difficulty_max",
)


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else _NONE


def generate(profile: ProfileData, template: str | None = None) -> str:
    """Render a Yutori Scout query from the profile.

    `template` is the active edited version, if any; otherwise the built-in
    one. Pure: no network, no clock, no database — so it can be unit-tested
    directly (tdd.md §4.4, M4-B3).
    """
    # Weight is included so Yutori can tell a primary interest from a marginal
    # one; topics are ordered heaviest-first for the same reason.
    topics = [
        f"{topic.name} (weight {int(topic.weight)}/100)"
        for topic in sorted(profile.topics, key=lambda t: t.weight, reverse=True)
    ]

    return (template or _TEMPLATE).format(
        topics=_bullets(topics),
        preferred_concepts=_bullets(profile.preferred_concepts),
        excluded_concepts=_bullets(profile.excluded_concepts),
        difficulty_min=profile.difficulty.minimum,
        difficulty_max=profile.difficulty.maximum,
    )
