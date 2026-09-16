import base64
import hashlib

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings


def _derive_fernet_key(secret: str) -> bytes:
    """Fernet needs a 32-byte urlsafe-base64 key; APP_SECRET_KEY is an
    arbitrary-length hex string, so hash it down to a fixed-size key first.
    """
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_fernet_key(settings.app_secret_key))


def encrypt_value(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


SESSION_COOKIE_NAME = "session"
# Long-lived since there's only ever one legitimate user (prd.md §27.1).
SESSION_MAX_AGE_SECONDS = 90 * 24 * 60 * 60

# A distinct salt from Fernet's own key derivation above, even though both
# ultimately derive from the same APP_SECRET_KEY — keeps the two uses
# cryptographically separate.
_session_serializer = URLSafeTimedSerializer(settings.app_secret_key, salt="session-cookie")


def create_session_token() -> str:
    return _session_serializer.dumps({"authenticated": True})


def verify_session_token(token: str) -> bool:
    try:
        _session_serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return True


# prd.md §27.1: every route requires a valid session except these — clickable
# from an email with no login (feedback, scout confirm), secured a different
# way (the webhook, by signature), needed unauthenticated (uptime checks), or
# part of the login mechanism itself.
_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/logout",
    "/auth/session",
    "/feedback",
    "/webhooks/yutori",
    "/health",
    "/ready",
}
_EXEMPT_PATH_PREFIXES = ("/scout/confirm/",)


def _is_exempt(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PATH_PREFIXES)


async def require_session(request: Request) -> None:
    if _is_exempt(request.url.path):
        return
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None or not verify_session_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
