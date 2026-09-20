"""Correcting what an account really cost.

The computed total sums `scout_runs.cost_usd` by fingerprint, so it is only as
complete as the run history — and `scout_runs` did not exist before M12, which
makes earlier spend invisible and unrecoverable. These tests pin the override
that lets the user state the real figure, and the reset that gives the
calculation back.

`conftest.protect_real_data` snapshots and restores `credentials`, so the rows
written here are put back verbatim when the session ends.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import async_session
from app.models.credential import Credential


async def _a_yutori_account_id() -> int | None:
    async with async_session() as session:
        credential = await session.scalar(
            select(Credential).where(Credential.key_name == "yutori_api_key")
        )
        return credential.id if credential else None


@pytest.fixture
async def account_id():
    found = await _a_yutori_account_id()
    if found is None:
        pytest.skip("no Yutori key stored to correct")
    yield found
    # Always hand the row back the way it was found, so a failure mid-test does
    # not leave a correction on a real account.
    async with async_session() as session:
        credential = await session.get(Credential, found)
        credential.spend_override_usd = None
        await session.commit()


def _account(client: TestClient, cookies: dict[str, str], account_id: int) -> dict:
    rows = client.get("/accounts", cookies=cookies).json()["accounts"]
    return next(row for row in rows if row["id"] == account_id)


@pytest.mark.anyio
async def test_an_override_replaces_the_displayed_total(
    client: TestClient, auth_cookies: dict[str, str], account_id: int
) -> None:
    response = client.put(
        f"/accounts/{account_id}/spend", json={"spend_usd": 0.70}, cookies=auth_cookies
    )
    assert response.status_code == 200

    row = _account(client, auth_cookies, account_id)
    assert row["spend_usd"] == 0.70
    assert row["spend_override_usd"] == 0.70


@pytest.mark.anyio
async def test_the_calculated_total_survives_alongside_the_correction(
    client: TestClient, auth_cookies: dict[str, str], account_id: int
) -> None:
    """Overwriting it would destroy the evidence that the two disagree, which
    is the thing worth seeing.
    """
    before = _account(client, auth_cookies, account_id)["computed_spend_usd"]

    client.put(f"/accounts/{account_id}/spend", json={"spend_usd": 12.34}, cookies=auth_cookies)

    row = _account(client, auth_cookies, account_id)
    assert row["computed_spend_usd"] == before
    assert row["spend_usd"] == 12.34


@pytest.mark.anyio
async def test_clearing_the_override_restores_the_calculation(
    client: TestClient, auth_cookies: dict[str, str], account_id: int
) -> None:
    """A correction must never be a one-way door."""
    computed = _account(client, auth_cookies, account_id)["computed_spend_usd"]

    client.put(f"/accounts/{account_id}/spend", json={"spend_usd": 99.0}, cookies=auth_cookies)
    client.put(f"/accounts/{account_id}/spend", json={"spend_usd": None}, cookies=auth_cookies)

    row = _account(client, auth_cookies, account_id)
    assert row["spend_override_usd"] is None
    assert row["spend_usd"] == computed


@pytest.mark.anyio
async def test_zero_is_a_real_correction_not_a_reset(
    client: TestClient, auth_cookies: dict[str, str], account_id: int
) -> None:
    """An account really can have cost nothing, and saying so must stick
    rather than falling back to the computed figure.
    """
    client.put(f"/accounts/{account_id}/spend", json={"spend_usd": 0}, cookies=auth_cookies)

    row = _account(client, auth_cookies, account_id)
    assert row["spend_override_usd"] == 0
    assert row["spend_usd"] == 0


@pytest.mark.anyio
async def test_a_negative_amount_is_refused(
    client: TestClient, auth_cookies: dict[str, str], account_id: int
) -> None:
    response = client.put(
        f"/accounts/{account_id}/spend", json={"spend_usd": -1}, cookies=auth_cookies
    )
    assert response.status_code == 422


def test_correcting_an_account_that_does_not_exist_is_a_404(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.put("/accounts/99999999/spend", json={"spend_usd": 1.0}, cookies=auth_cookies)
    assert response.status_code == 404


def test_setting_spend_requires_a_session(client: TestClient) -> None:
    assert client.put("/accounts/1/spend", json={"spend_usd": 1.0}).status_code == 401
