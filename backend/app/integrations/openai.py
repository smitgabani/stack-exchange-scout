import json
from typing import Any

import httpx

from app.integrations.llm import CHALLENGE_SCHEMA, LLMError

BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"


class OpenAIProvider:
    """OpenAI behind the same interface as Gemini (M7-B2).

    Optional and unused by default — `profile.llm.provider` selects it, and M2
    already refuses to switch without a stored key. Exists so the provider
    choice stays a config decision rather than a rewrite.
    """

    name = "openai"

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout

    async def generate_json(self, *, system_instruction: str, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "challenge", "schema": CHALLENGE_SCHEMA, "strict": False},
            },
            "temperature": 0.7,
        }

        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=self._timeout) as client:
                response = await client.post(
                    "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(f"OpenAI returned {response.status_code}: {response.text[:400]}")

        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected OpenAI response shape: {str(body)[:300]}") from exc

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI did not return valid JSON: {text[:300]}") from exc

        if not isinstance(parsed, dict):
            raise LLMError("OpenAI returned JSON that is not an object")
        return parsed
