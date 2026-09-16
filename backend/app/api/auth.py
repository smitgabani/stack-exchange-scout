from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    verify_session_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class SessionStatus(BaseModel):
    authenticated: bool


@router.post("/login", response_model=SessionStatus)
async def login(body: LoginRequest, response: Response) -> SessionStatus:
    if body.password != settings.app_access_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return SessionStatus(authenticated=True)


@router.post("/logout", response_model=SessionStatus)
async def logout(response: Response) -> SessionStatus:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return SessionStatus(authenticated=False)


@router.get("/session", response_model=SessionStatus)
async def session(request: Request) -> SessionStatus:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    authenticated = token is not None and verify_session_token(token)
    return SessionStatus(authenticated=authenticated)
