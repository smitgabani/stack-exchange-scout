from fastapi.testclient import TestClient


def test_profile_requires_session(client: TestClient) -> None:
    assert client.get("/profile").status_code == 401


def test_get_profile_returns_full_shape(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.get("/profile", cookies=auth_cookies)
    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    for key in ("topics", "preferred_concepts", "excluded_concepts", "difficulty", "digest", "llm"):
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


# --- M3: server-side validation ---


def test_patch_profile_topic_weight_out_of_bounds_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch("/profile", json={"topics": [{"name": "python", "weight": 150}]}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_duplicate_topic_names_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch(
        "/profile",
        json={"topics": [{"name": "Python", "weight": 50}, {"name": "python", "weight": 30}]},
        cookies=auth_cookies,
    )
    assert response.status_code == 422


def test_patch_profile_topics_valid_round_trip(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch("/profile", json={"topics": [{"name": "Rust", "weight": 75}]}, cookies=auth_cookies)
    assert response.status_code == 200
    assert response.json()["data"]["topics"] == [{"name": "Rust", "weight": 75}]


def test_patch_profile_difficulty_min_greater_than_max_rejected(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.patch("/profile", json={"difficulty": {"minimum": 5, "maximum": 2}}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_difficulty_out_of_1_to_5_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch("/profile", json={"difficulty": {"minimum": 0, "maximum": 5}}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_digest_bounds_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    assert client.patch("/profile", json={"digest": {"questions": 999}}, cookies=auth_cookies).status_code == 422
    assert client.patch("/profile", json={"digest": {"frequency_days": 0}}, cookies=auth_cookies).status_code == 422


def test_patch_profile_max_answers_out_of_bounds_rejected(client: TestClient, auth_cookies: dict[str, str]) -> None:
    response = client.patch("/profile", json={"question_preferences": {"max_answers": 999}}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_exclude_flags_always_coerced_true(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.patch(
        "/profile",
        json={"question_preferences": {"exclude_closed": False, "exclude_duplicates": False}},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    prefs = response.json()["data"]["question_preferences"]
    assert prefs["exclude_closed"] is True
    assert prefs["exclude_duplicates"] is True


def test_patch_profile_duplicate_preferred_concepts_rejected(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.patch("/profile", json={"preferred_concepts": ["debugging", "Debugging"]}, cookies=auth_cookies)
    assert response.status_code == 422


def test_patch_profile_concept_overlap_between_preferred_and_excluded_rejected(
    client: TestClient, auth_cookies: dict[str, str]
) -> None:
    response = client.patch(
        "/profile",
        json={"preferred_concepts": ["performance"], "excluded_concepts": ["performance"]},
        cookies=auth_cookies,
    )
    assert response.status_code == 422
