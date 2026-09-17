from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.repositories import profile_repository
from app.schemas.profile import ProfileData
from app.services.credentials_service import has_api_key


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """JSON-Merge-Patch-style merge (RFC 7396): only keys present in `patch`
    are touched, at any nesting level; everything else in `base` is kept.
    """
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


async def get_or_create_profile(db: AsyncSession) -> Profile:
    profile = await profile_repository.get(db)
    if profile is None:
        profile = await profile_repository.create_default(db)
    return profile


async def apply_patch(db: AsyncSession, patch: dict[str, Any]) -> Profile:
    profile = await get_or_create_profile(db)

    unknown_keys = set(patch) - set(ProfileData.model_fields)
    if unknown_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown profile field(s): {sorted(unknown_keys)}",
        )

    merged = _deep_merge(profile.data, patch)
    try:
        validated = ProfileData.model_validate(merged)
    except ValidationError as exc:
        # include_context=False: our custom validators raise plain
        # ValueError, which Pydantic surfaces via errors()[i]["ctx"]["error"]
        # as the raw exception object — not JSON-serializable, which would
        # otherwise crash the response instead of returning a clean 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_context=False, include_url=False, include_input=False),
        ) from exc

    if validated.llm.provider == "openai" and not await has_api_key(db, "openai_api_key"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot switch llm.provider to 'openai' without a stored OpenAI key",
        )

    saved = await profile_repository.save(db, profile, validated.model_dump(mode="json"))

    # Keep the Scout's query in step with the profile (prd.md §8 step 4). Runs
    # after the save and never raises, so Yutori being down can't cost the user
    # their edit (tdd.md §8.2) — a failure is recorded on the scout row and
    # surfaced in the Settings sync status instead. Won't create a Scout; that
    # would be a billable run nobody asked for.
    from app.services import scout_service  # local import: avoids a cycle

    await scout_service.sync(db, validated)
    return saved
