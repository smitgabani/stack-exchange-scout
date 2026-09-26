from typing import Any, Protocol


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

    async def generate_json(
        self, *, system_instruction: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Return structured JSON conforming to `schema`.

        The schema is passed in rather than fixed because a challenge format
        selects which blocks to ask for, and the shape has to match. It is
        enforced twice: sent to the provider as a structured-output schema, and
        validated again on the way back, because a provider promising JSON is
        not the same as a guarantee.
        """
        ...
