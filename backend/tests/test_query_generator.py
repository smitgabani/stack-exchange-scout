from app.schemas.profile import Difficulty, ProfileData, Topic
from app.services import query_generator


def _profile(**overrides) -> ProfileData:
    defaults = {
        "topics": [Topic(name="python", weight=100), Topic(name="postgresql", weight=60)],
        "preferred_concepts": ["debugging", "performance"],
        "excluded_concepts": ["homework"],
        "difficulty": Difficulty(minimum=3, maximum=5),
    }
    return ProfileData(**{**defaults, **overrides})


def test_topics_appear_in_query() -> None:
    query = query_generator.generate(_profile())
    assert "python" in query
    assert "postgresql" in query


def test_topics_ordered_by_weight_descending() -> None:
    query = query_generator.generate(_profile())
    assert query.index("python") < query.index("postgresql")


def test_preferred_and_excluded_concepts_appear() -> None:
    query = query_generator.generate(_profile())
    assert "debugging" in query
    assert "performance" in query
    assert "homework" in query


def test_difficulty_range_is_interpolated() -> None:
    query = query_generator.generate(_profile(difficulty=Difficulty(minimum=2, maximum=4)))
    assert "2-4 out of 5" in query


def test_empty_lists_do_not_produce_dangling_sections() -> None:
    query = query_generator.generate(
        _profile(topics=[], preferred_concepts=[], excluded_concepts=[])
    )
    assert "(none specified)" in query
    # The instruction to Yutori must survive an empty profile.
    assert "Do not solve the questions." in query


def test_is_pure_and_deterministic() -> None:
    profile = _profile()
    assert query_generator.generate(profile) == query_generator.generate(profile)
