from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
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
    profile = await db.scalar(select(Profile).limit(1))
    if profile is None:
        profile = Profile(data=ProfileData().model_dump(mode="json"), version=1)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


async def get_profile_data(db: AsyncSession) -> ProfileData:
    return ProfileData.model_validate((await get_or_create_profile(db)).data)


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

    # Pushes nothing to Yutori: scouts render their query from the profile when
    # they run, and a live monitor is updated deliberately from its own page.
    profile.data = validated.model_dump(mode="json")
    profile.version += 1
    await db.commit()
    await db.refresh(profile)
    return profile
