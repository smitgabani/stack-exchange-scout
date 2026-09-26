"""The Yutori helpers the scout workspace is built on. Pure functions: nothing
here touches the database or Yutori's API.
"""

from app.services import scout_service
from app.services.ingest_service import parse_candidates
from app.services.task_settings import mask_webhook_url


def test_update_envelope_prefers_structured_result():
    """The updates API has no report_content, so pulled updates are reshaped to
    look like a webhook body — which keeps webhook parsing untouched."""
    envelope = scout_service.update_to_webhook_envelope(
        {
            "id": "u1",
            "content": "prose that should be ignored",
            "structured_result": {"questions": [{"url": "https://stackoverflow.com/questions/999"}]},
        }
    )
    assert parse_candidates(envelope) == [{"url": "https://stackoverflow.com/questions/999"}]


def test_update_envelope_falls_back_to_prose_content():
    envelope = scout_service.update_to_webhook_envelope(
        {"id": "u2", "content": "look at https://stackoverflow.com/questions/4242 today"}
    )
    assert parse_candidates(envelope) == [{"question_id": "4242"}]


def test_webhook_url_is_masked_before_leaving_the_backend():
    """The registered webhook URL carries YUTORI_WEBHOOK_SECRET, which is the
    only thing authenticating inbound candidate data."""
    masked = mask_webhook_url("https://api.example.com/webhooks/yutori?token=supersecret")

    assert masked == "https://api.example.com/webhooks/yutori"
    assert "supersecret" not in masked


def test_mask_handles_missing_and_malformed_urls():
    assert mask_webhook_url(None) is None
    assert mask_webhook_url("not-a-url?token=secret") == "(configured)"


def test_fingerprint_identifies_without_revealing():
    key = "yut_super_secret_key_value"
    printed = scout_service.fingerprint(key)

    assert len(printed) == 16
    assert printed == scout_service.fingerprint(key)
    assert printed != scout_service.fingerprint(key + "x")
    assert key not in printed
