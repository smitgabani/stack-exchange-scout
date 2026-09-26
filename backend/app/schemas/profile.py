from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Topic(BaseModel):
    name: str
    weight: float = Field(default=50.0, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("topic name must not be blank")
        return cleaned


class Difficulty(BaseModel):
    minimum: int = Field(default=3, ge=1, le=5)
    maximum: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def check_min_le_max(self) -> "Difficulty":
        if self.minimum > self.maximum:
            raise ValueError("difficulty.minimum must be <= difficulty.maximum")
        return self


class QuestionPreferences(BaseModel):
    prefer_unanswered: bool = True
    max_answers: int = Field(default=3, ge=0, le=10)
    prefer_recent: bool = True
    exclude_closed: bool = True
    exclude_duplicates: bool = True

    @model_validator(mode="after")
    def force_always_on_exclusions(self) -> "QuestionPreferences":
        # prd.md §14: always on, regardless of client input (M3-B5) — not
        # rejected, silently coerced, so a client can't accidentally (or
        # deliberately) turn these off.
        self.exclude_closed = True
        self.exclude_duplicates = True
        return self


class Digest(BaseModel):
    frequency_days: int = Field(default=3, ge=1, le=30)
    questions: int = Field(default=5, ge=1, le=10)


class Llm(BaseModel):
    provider: Literal["gemini", "openai"] = "gemini"


def _normalize_concepts(value: list[str]) -> list[str]:
    cleaned = [v.strip() for v in value]
    if any(not v for v in cleaned):
        raise ValueError("concepts must not be blank")
    lowered = [v.lower() for v in cleaned]
    if len(lowered) != len(set(lowered)):
        raise ValueError("duplicate concept in list")
    return cleaned


class ProfileData(BaseModel):
    """The full profile document shape (prd.md §7.1), with M3's server-side
    validation: topic weight/name-uniqueness bounds, concept dedup and
    preferred/excluded overlap checks, difficulty min<=max, digest bounds,
    and question-preference exclusions forced always-on.
    """

    topics: list[Topic] = Field(default_factory=list)
    preferred_concepts: list[str] = Field(default_factory=list)
    excluded_concepts: list[str] = Field(default_factory=list)
    difficulty: Difficulty = Field(default_factory=Difficulty)
    question_preferences: QuestionPreferences = Field(default_factory=QuestionPreferences)
    digest: Digest = Field(default_factory=Digest)
    llm: Llm = Field(default_factory=Llm)

    @field_validator("preferred_concepts", "excluded_concepts")
    @classmethod
    def no_blank_or_duplicate_concepts(cls, value: list[str]) -> list[str]:
        return _normalize_concepts(value)

    @model_validator(mode="after")
    def check_topic_names_unique(self) -> "ProfileData":
        names = [t.name.lower() for t in self.topics]
        if len(names) != len(set(names)):
            raise ValueError("topic names must be unique")
        return self

    @model_validator(mode="after")
    def check_concepts_no_overlap(self) -> "ProfileData":
        preferred_lower = {c.lower() for c in self.preferred_concepts}
        excluded_lower = {c.lower() for c in self.excluded_concepts}
        overlap = preferred_lower & excluded_lower
        if overlap:
            raise ValueError(f"concept(s) cannot be both preferred and excluded: {sorted(overlap)}")
        return self


class ProfileResponse(BaseModel):
    data: ProfileData
    version: int
