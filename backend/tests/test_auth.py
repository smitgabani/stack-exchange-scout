from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import _is_exempt
from app.main import app

client = TestClient(app)


def test_exempt_paths() -> None:
    assert _is_exempt("/auth/login")
    assert _is_exempt("/auth/logout")
    assert _is_exempt("/auth/session")
    assert _is_exempt("/feedback")
    assert _is_exempt("/webhooks/yutori")
    assert _is_exempt("/health")
    assert _is_exempt("/ready")
    assert _is_exempt("/scout/confirm/42")
    assert not _is_exempt("/profile")


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


def test_session_unauthenticated_without_cookie() -> None:
    assert client.get("/auth/session").json() == {"authenticated": False}


def test_session_authenticated_with_valid_cookie() -> None:
    login = client.post("/auth/login", json={"password": settings.app_access_password})
    response = client.get("/auth/session", cookies={"session": login.cookies["session"]})
    assert response.json() == {"authenticated": True}


def test_tampered_cookie_rejected() -> None:
    response = client.get("/auth/session", cookies={"session": "not-a-real-token"})
    assert response.json() == {"authenticated": False}


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
