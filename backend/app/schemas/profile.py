from typing import Literal

from pydantic import BaseModel, Field


class Topic(BaseModel):
    name: str
    weight: float = 1.0


class Difficulty(BaseModel):
    minimum: int = 3
    maximum: int = 5


class QuestionPreferences(BaseModel):
    prefer_unanswered: bool = True
    max_answers: int = 3
    prefer_recent: bool = True
    exclude_closed: bool = True
    exclude_duplicates: bool = True


class Digest(BaseModel):
    frequency_days: int = 3
    questions: int = 5


class Scout(BaseModel):
    mode: Literal["setup", "automatic"] = "setup"
    confirm_before_run: bool = True
    interval_days: int = 3


class Llm(BaseModel):
    provider: Literal["gemini", "openai"] = "gemini"


class ProfileData(BaseModel):
    """The full profile document shape (prd.md §7.1).

    Bounds validation on individual fields (topic weight ranges, difficulty
    min<=max, etc.) is M3's scope — this only enforces structure/types so a
    genuinely malformed patch is still rejected here in M2.
    """

    topics: list[Topic] = Field(default_factory=list)
    preferred_concepts: list[str] = Field(default_factory=list)
    excluded_concepts: list[str] = Field(default_factory=list)
    difficulty: Difficulty = Field(default_factory=Difficulty)
    question_preferences: QuestionPreferences = Field(default_factory=QuestionPreferences)
    digest: Digest = Field(default_factory=Digest)
    scout: Scout = Field(default_factory=Scout)
    llm: Llm = Field(default_factory=Llm)


class ProfileResponse(BaseModel):
    data: ProfileData
    version: int
