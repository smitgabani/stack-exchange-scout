from typing import Any, Protocol

# The five fields a challenge must contain (tdd.md §8.7). Enforced twice: sent
# to the provider as a structured-output schema, and validated again on the way
# back, because a provider promising JSON is not the same as a guarantee.
CHALLENGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "problem_summary": {"type": "string"},
        "why_interesting": {"type": "string"},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "starting_direction": {"type": "string"},
        "hints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "text": {"type": "string"}},
                "required": ["label", "text"],
            },
        },
        "estimated_difficulty": {"type": "integer"},
    },
    "required": [
        "problem_summary",
        "why_interesting",
        "concepts",
        "starting_direction",
        "hints",
    ],
}


class LLMError(RuntimeError):
    """The provider failed, or returned something unusable."""


class LLMProvider(Protocol):
    """What the challenge service needs from a model provider.

    Kept deliberately narrow so swapping Gemini for OpenAI touches nothing
    else (tdd.md §7.3) — and so tests can substitute a fake without any
    network access.
    """

    name: str
    model: str

    async def generate_json(self, *, system_instruction: str, prompt: str) -> dict[str, Any]:
        """Return structured JSON conforming to CHALLENGE_SCHEMA."""
        ...
