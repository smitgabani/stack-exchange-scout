import pytest
from fastapi import HTTPException

from app.api.deps import require_gemini_key, require_yutori_key
from app.core.security import decrypt_value, encrypt_value
from app.services.credentials_service import has_api_key, set_api_key


def test_fernet_round_trip() -> None:
    ciphertext = encrypt_value("a-real-looking-api-key")
    assert ciphertext != "a-real-looking-api-key"
    assert decrypt_value(ciphertext) == "a-real-looking-api-key"


@pytest.mark.anyio
async def test_require_yutori_key_rejects_when_missing_then_allows_once_set(db_session) -> None:
    # Only meaningful to assert "rejected" on a fresh DB (e.g. CI); against a
    # persistent local dev DB where this key was already set, skip to the
    # part that's always true.
    if not await has_api_key(db_session, "yutori_api_key"):
        with pytest.raises(HTTPException) as exc_info:
            await require_yutori_key(db=db_session)
        assert exc_info.value.status_code == 403

    await set_api_key(db_session, "yutori_api_key", "test-key")
    await require_yutori_key(db=db_session)  # no exception


@pytest.mark.anyio
async def test_require_gemini_key_rejects_when_missing_then_allows_once_set(db_session) -> None:
    if not await has_api_key(db_session, "gemini_api_key"):
        with pytest.raises(HTTPException) as exc_info:
            await require_gemini_key(db=db_session)
        assert exc_info.value.status_code == 403

    await set_api_key(db_session, "gemini_api_key", "test-key")
    await require_gemini_key(db=db_session)  # no exception
