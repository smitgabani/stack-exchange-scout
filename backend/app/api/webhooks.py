import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.services import ingest_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_token(token: str | None) -> None:
    """Authenticate an inbound webhook.

    Yutori offers no payload signing, so authenticity rests on a secret we
    generate and embed in the URL we register with them. Compared with
    compare_digest to avoid leaking the secret through timing. Fails closed
    when unconfigured — an unauthenticated candidate-injection endpoint is
    exactly what tdd.md §9.3 warns against.
    """
    if not settings.yutori_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret is not configured",
        )
    if not token or not hmac.compare_digest(token, settings.yutori_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")


@router.post("/yutori")
async def yutori_webhook(
    request: Request,
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Durable inbox for Yutori Scout updates.

    Does the minimum and returns: verify, persist, acknowledge. Enrichment is a
    separate stage, because this process runs on a scale-to-zero host that can
    be stopped moments after the response flushes, and Yutori gives up after 3
    attempts in ~30s with no later redelivery. Anything not committed here
    would be lost for good.
    """
    _verify_token(token)

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Body is not valid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object")

    event = await ingest_service.claim_event(db, payload)
    if event is None:
        # Either a redelivery of an event already stored, or one with no usable
        # id. Both are 200 — retrying wouldn't help Yutori.
        return {"status": "duplicate"}

    return {"status": "accepted", "event_id": str(event.id)}
