from collections import Counter
from datetime import UTC, datetime, timedelta

from app.models.question import Question
from app.schemas.profile import Difficulty, ProfileData, QuestionPreferences, Topic
from app.services import ranking_service

NOW = datetime(2026, 9, 17, tzinfo=UTC)
_BODY = "<p>A detailed question with substance. </p>" * 10


def _profile(**overrides) -> ProfileData:
    defaults = {
        "topics": [Topic(name="python", weight=80), Topic(name="asyncio", weight=60)],
        "preferred_concepts": ["performance"],
        "excluded_concepts": [],
        "difficulty": Difficulty(minimum=3, maximum=5),
    }
    return ProfileData(**{**defaults, **overrides})


def _question(**overrides) -> Question:
    defaults = {
        "stackoverflow_question_id": 1,
        "canonical_url": "https://stackoverflow.com/questions/1",
        "url": "https://stackoverflow.com/questions/1",
        "title": "Why does asyncio.gather run sequentially?",
        "body": _BODY,
        "tags": ["python", "asyncio"],
        "score": 5,
        "answer_count": 1,
        "accepted_answer_id": None,
        "difficulty": 4,
        "question_created_at": NOW - timedelta(days=5),
        "last_activity_at": NOW - timedelta(days=1),
        "status": "candidate",
    }
    return Question(**{**defaults, **overrides})


# --- topic relevance (weight 30) ---


def test_topic_relevance_uses_the_heaviest_matching_topic() -> None:
    question = _question(tags=["python"], title="plain")
    assert ranking_service.score_topic_relevance(question, _profile()) == 80


def test_topic_relevance_bonuses_multiple_matches() -> None:
    both = ranking_service.score_topic_relevance(_question(tags=["python", "asyncio"]), _profile())
    one = ranking_service.score_topic_relevance(_question(tags=["python"], title="plain"), _profile())
    assert both > one


def test_topic_relevance_is_zero_with_no_topic_match() -> None:
    # The M6-TEST requirement: an off-topic question scores near-zero here.
    question = _question(tags=["haskell"], title="Monad transformers")
    assert ranking_service.score_topic_relevance(question, _profile()) == 0


def test_topic_relevance_penalises_excluded_concepts() -> None:
    profile = _profile(excluded_concepts=["homework"])
    with_excluded = _question(body=_BODY + " this is homework ")
    assert ranking_service.score_topic_relevance(
        with_excluded, profile
    ) < ranking_service.score_topic_relevance(_question(), profile)


def test_topic_relevance_is_neutral_when_no_topics_configured() -> None:
    assert ranking_service.score_topic_relevance(_question(), _profile(topics=[])) == 50


# --- technical depth (25) ---


def test_technical_depth_rises_with_difficulty() -> None:
    profile = _profile(difficulty=Difficulty(minimum=1, maximum=5))
    easy = ranking_service.score_technical_depth(_question(difficulty=1), profile)
    hard = ranking_service.score_technical_depth(_question(difficulty=5), profile)
    assert hard > easy


def test_technical_depth_penalises_below_the_requested_window() -> None:
    profile = _profile(difficulty=Difficulty(minimum=4, maximum=5))
    assert ranking_service.score_technical_depth(
        _question(difficulty=1), profile
    ) < ranking_service.score_technical_depth(_question(difficulty=4), profile)


# --- solve opportunity (20) ---


def test_accepted_answer_sharply_reduces_solve_opportunity() -> None:
    profile = _profile()
    unanswered = ranking_service.score_solve_opportunity(_question(answer_count=0), profile)
    accepted = ranking_service.score_solve_opportunity(
        _question(answer_count=1, accepted_answer_id=99), profile
    )
    assert unanswered > accepted


def test_too_many_answers_zeroes_solve_opportunity() -> None:
    profile = _profile(question_preferences=QuestionPreferences(max_answers=3))
    assert ranking_service.score_solve_opportunity(_question(answer_count=10), profile) == 0


def test_thin_question_caps_solve_opportunity() -> None:
    assert ranking_service.score_solve_opportunity(_question(body="tiny", answer_count=0), _profile()) <= 40


# --- recency (10) ---


def test_recency_decays_with_age() -> None:
    profile = _profile()
    fresh = ranking_service.score_recency(_question(question_created_at=NOW), profile, NOW)
    old = ranking_service.score_recency(
        _question(question_created_at=NOW - timedelta(days=365)), profile, NOW
    )
    assert fresh > old
    assert fresh >= 95


def test_recency_is_neutral_when_the_date_is_unknown() -> None:
    question = _question(question_created_at=None, last_activity_at=None)
    assert ranking_service.score_recency(question, _profile(), NOW) == 50


# --- quality (10) ---


def test_quality_rises_with_votes() -> None:
    assert ranking_service.score_quality(_question(score=100)) > ranking_service.score_quality(
        _question(score=0)
    )


def test_quality_handles_negative_votes_without_error() -> None:
    assert ranking_service.score_quality(_question(score=-5)) >= 0


# --- novelty (5) ---


def test_novelty_penalises_recently_seen_tags() -> None:
    fresh = ranking_service.score_novelty(_question(), Counter())
    repeated = ranking_service.score_novelty(_question(), Counter({"python": 3, "asyncio": 2}))
    assert fresh == 100
    assert repeated < fresh


# --- total + guard ---


def test_total_is_the_documented_weighted_sum() -> None:
    scores = ranking_service.Scores(
        topic_relevance=100,
        technical_depth=100,
        solve_opportunity=100,
        recency=100,
        quality=100,
        novelty=100,
    )
    assert scores.total == 100.0


def test_scoring_is_deterministic() -> None:
    question, profile = _question(), _profile()
    first = ranking_service.score(question, profile, now=NOW)
    second = ranking_service.score(question, profile, now=NOW)
    assert first == second


def _scored(question: Question, profile: ProfileData) -> Question:
    scores = ranking_service.score(question, profile, now=NOW)
    question.candidate_score = scores.total
    question.topic_relevance = scores.topic_relevance
    question.solve_opportunity = scores.solve_opportunity
    return question


def test_a_strong_candidate_clears_the_digest_bar() -> None:
    # Recent, on-topic, one unaccepted answer — the shape this product exists
    # to surface.
    question = _scored(_question(question_created_at=NOW - timedelta(days=2)), _profile())
    assert ranking_service.is_digest_eligible(
        question
    ), f"expected eligible, scored {question.candidate_score}"


def test_off_topic_question_is_blocked_even_with_a_high_total() -> None:
    """Depth and quality must not smuggle an off-topic question into a digest."""
    question = _question()
    question.candidate_score = 95.0
    question.topic_relevance = 10
    question.solve_opportunity = 100
    assert ranking_service.is_digest_eligible(question) is False


def test_thoroughly_answered_question_is_blocked_even_with_a_high_total() -> None:
    """Caught by scoring real data: a famous, on-topic, well-written question
    with 51 answers and an accepted one cleared the total on topic + depth +
    quality alone, despite there being nothing left to solve.
    """
    question = _question()
    question.candidate_score = 90.0
    question.topic_relevance = 90
    question.solve_opportunity = 0
    assert ranking_service.is_digest_eligible(question) is False


def test_unscored_question_is_never_eligible() -> None:
    assert ranking_service.is_digest_eligible(_question()) is False
