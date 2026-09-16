from fastapi.testclient import TestClient


def test_profile_requires_session(client: TestClient) -> None:
    assert client.get("/profile").status_code == 401


def test_get_profile_returns_full_shape(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.get("/profile", cookies=auth_cookies)
    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    for key in ("topics", "preferred_concepts", "excluded_concepts", "difficulty", "digest", "scout", "llm"):
        assert key in body["data"]


def test_patch_profile_increments_version_by_exactly_one(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    before = client.get("/profile", cookies=auth_cookies).json()["version"]
    response = client.patch("/profile", json={"digest": {"questions": 7}}, cookies=auth_cookies)
    assert response.status_code == 200
    assert response.json()["version"] == before + 1


def test_patch_profile_preserves_untouched_sibling_fields(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    client.patch("/profile", json={"digest": {"frequency_days": 9}}, cookies=auth_cookies)
    response = client.patch("/profile", json={"digest": {"questions": 2}}, cookies=auth_cookies)
    assert response.json()["data"]["digest"] == {"frequency_days": 9, "questions": 2}


def test_patch_profile_unknown_top_level_field_rejected(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.patch("/profile", json={"not_a_real_field": 1}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_malformed_value_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch("/profile", json={"llm": {"provider": "not-a-real-provider"}}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_switch_to_openai_without_key_rejected(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    # Correct on a fresh database (e.g. CI's ephemeral Postgres); against a
    # persistent local dev DB where an OpenAI key was set in an earlier
    # manual/test run, this precondition no longer holds.
    status = client.get("/settings/openai-key/status", cookies=auth_cookies).json()
    if status["connected"]:
        return

    response = client.patch("/profile", json={"llm": {"provider": "openai"}}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_switch_to_openai_with_key_succeeds(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    client.post("/settings/openai-key", json={"api_key": "sk-test-not-a-real-key"}, cookies=auth_cookies)
    response = client.patch("/profile", json={"llm": {"provider": "openai"}}, cookies=auth_cookies)
    assert response.status_code == 200
    assert response.json()["data"]["llm"]["provider"] == "openai"
