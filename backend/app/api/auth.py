from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    verify_session_token,
)
from app.services.credentials_service import has_api_key

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


class BootstrapOut(BaseModel):
    """Everything the app shell needs before it can render anything."""

    authenticated: bool
    # Both keys present. Onboarding is the gate on this, and asking for it
    # separately was two more requests.
    onboarding_complete: bool
    yutori_key: bool
    gemini_key: bool


@router.get("/bootstrap", response_model=BootstrapOut)
async def bootstrap(request: Request, db: AsyncSession = Depends(get_db)) -> BootstrapOut:
    """The three questions every page load used to ask separately.

    `AuthGate` asked whether there was a session, then `OnboardingGate` asked
    whether each of the two API keys was stored — three round trips before
    anything rendered, each one a Vercel function proxying to Fly.

    The key lookups are skipped entirely when there is no session, because the
    answer is not usable and the database need not be woken to produce it.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    authenticated = token is not None and verify_session_token(token)
    if not authenticated:
        return BootstrapOut(
            authenticated=False,
            onboarding_complete=False,
            yutori_key=False,
            gemini_key=False,
        )

    yutori = await has_api_key(db, "yutori_api_key")
    gemini = await has_api_key(db, "gemini_api_key")
    return BootstrapOut(
        authenticated=True,
        onboarding_complete=yutori and gemini,
        yutori_key=yutori,
        gemini_key=gemini,
    )
