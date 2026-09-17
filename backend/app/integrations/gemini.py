import json
from typing import Any

import httpx

from app.integrations.llm import CHALLENGE_SCHEMA, LLMError

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.1-flash-lite"


class GeminiProvider:
    """Gemini via its REST API.

    Uses httpx rather than the official SDK to stay consistent with the other
    integrations and avoid another dependency for what is one POST.
    """

    name = "gemini"

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout

    async def generate_json(self, *, system_instruction: str, prompt: str) -> dict[str, Any]:
        payload = {
            # The system instruction is sent separately from the untrusted
            # question content, so the model sees a clear boundary between its
            # orders and the data it is reasoning about.
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_json_schema": CHALLENGE_SCHEMA,
                "temperature": 0.7,
            },
        }

        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=self._timeout) as client:
                response = await client.post(
                    f"/models/{self.model}:generateContent",
                    json=payload,
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc

        if response.status_code >= 400:
            # Never echo the request — it carries the API key header and the
            # full question text.
            raise LLMError(f"Gemini returned {response.status_code}: {response.text[:400]}")

        return self._extract_json(response.json())

    @staticmethod
    def _extract_json(body: dict[str, Any]) -> dict[str, Any]:
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected Gemini response shape: {str(body)[:300]}") from exc

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini did not return valid JSON: {text[:300]}") from exc

        if not isinstance(parsed, dict):
            raise LLMError("Gemini returned JSON that is not an object")
        return parsed
