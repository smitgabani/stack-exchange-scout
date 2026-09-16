import pytest
from fastapi.testclient import TestClient

PROVIDERS = ["yutori", "gemini", "openai"]


def test_settings_require_session(client: TestClient) -> None:
    assert client.get("/settings/yutori-key/status").status_code == 401
    assert client.post("/settings/yutori-key", json={"api_key": "x"}).status_code == 401


@pytest.mark.parametrize("provider", PROVIDERS)
def test_set_key_reports_connected_status_never_the_key_itself(
    client: TestClient, auth_cookies: dict[str, str], provider: str
) -> None:
    response = client.post(f"/settings/{provider}-key", json={"api_key": "super-secret-value"}, cookies=auth_cookies)
    assert response.status_code == 200
    body = response.json()
    assert body == {"connected": True}
    assert "super-secret-value" not in response.text

    status = client.get(f"/settings/{provider}-key/status", cookies=auth_cookies)
    assert status.json() == {"connected": True}
