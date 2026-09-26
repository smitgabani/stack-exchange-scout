from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import _EXEMPT_PATHS
from app.main import app

client = TestClient(app)


def test_exempt_paths() -> None:
    assert _EXEMPT_PATHS == {
        "/auth/login",
        "/auth/logout",
        "/auth/bootstrap",
        "/webhooks/yutori",
        "/health",
        "/ready",
    }
    assert "/profile" not in _EXEMPT_PATHS


def test_login_wrong_password_rejected() -> None:
    response = client.post("/auth/login", json={"password": "wrong"})
    assert response.status_code == 401


def test_login_correct_password_sets_signed_httponly_secure_cookie() -> None:
    response = client.post("/auth/login", json={"password": settings.app_access_password})
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie


def test_bootstrap_unauthenticated_without_cookie() -> None:
    assert client.get("/auth/bootstrap").json()["authenticated"] is False


def test_tampered_cookie_rejected() -> None:
    assert client.get("/", cookies={"session": "not-a-real-token"}).status_code == 401


def test_logout_clears_session() -> None:
    login = client.post("/auth/login", json={"password": settings.app_access_password})
    response = client.post("/auth/logout", cookies={"session": login.cookies["session"]})
    assert response.json() == {"authenticated": False}


def test_protected_route_requires_session() -> None:
    assert client.get("/").status_code == 401


def test_protected_route_accessible_with_valid_session() -> None:
    login = client.post("/auth/login", json={"password": settings.app_access_password})
    response = client.get("/", cookies={"session": login.cookies["session"]})
    assert response.status_code == 200
