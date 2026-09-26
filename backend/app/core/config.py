from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated environment configuration.

    Values are read from real environment variables first (what Fly.io sets
    in production), falling back to a local `.env` file for development.
    Missing required fields raise a validation error immediately on import,
    so a misconfigured deploy fails at startup rather than on the first
    request that happens to need the missing value.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    # "queue" pools connections and reuses them; "null" opens a fresh one per
    # session. Production wants the pool — it saves ~290ms of TLS and auth per
    # session. The test suite must not have it: pytest-anyio builds a new event
    # loop per test, and a pooled asyncpg connection belongs to the loop that
    # opened it, so reuse across loops raises "attached to a different loop".
    # Set by tests/conftest.py; nothing else should change it.
    db_pool: str = "queue"
    # Comma-separated list. Defaults to the Next.js dev server; the deployed
    # Vercel URL gets added here once M0-F2 exists.
    cors_origins: str = "http://localhost:3000"

    # The single shared password gating the whole app (prd.md §27.1) — no
    # user accounts, just one password. Compared directly in /auth/login.
    app_access_password: str
    # Signs the session cookie and encrypts stored API keys (prd.md §27) —
    # one key for both, no second signing secret needed.
    app_secret_key: str

    # Yutori has no webhook signing mechanism of its own, so authenticity rests
    # on an unguessable token we put in the registered webhook URL and compare
    # in constant time. Empty means "not configured" and the webhook fails
    # closed rather than accepting anonymous candidate data.
    yutori_webhook_secret: str = ""
    # This backend's own public origin, used to build the webhook URL handed to
    # Yutori. Must be HTTPS and externally reachable — Yutori rejects anything
    # else, and localhost obviously can't receive callbacks.
    public_base_url: str = ""
    # Per-run Yutori price, in config rather than inline because their pricing
    # can change (tdd.md §4.3a). Drives the M9 spend estimate. Confirmed against
    # docs.yutori.com/pricing: $0.35 per scout-run, $5 free credits per account.
    yutori_run_cost_usd: float = 0.35

    # After this long with no update, a run is treated as finished and the Scout
    # is parked. A run that finds nothing never sends a webhook, so without this
    # the Scout would sit "running" forever — and a stuck run is expensive in a
    # second way, because the Scout page polls while one is in flight. Set from
    # the one real run observed end to end, which took about 12 minutes.
    scout_run_timeout_seconds: int = 2700
    # What a run's Scout interval is set to. Long on purpose: if parking fails,
    # this is what stops the Scout billing again before anyone notices.
    scout_run_interval_seconds: int = 30 * 24 * 3600

    # The quality bar for entering a digest. Deliberately config, not profile:
    # prd.md §26 forbids lowering the threshold to fill a digest, so it must
    # not be user-tunable. Calibrated so a solid candidate (~67) clears it and
    # a merely-plausible one (~32) doesn't.
    digest_min_score: float = 55.0
    # A second, independent bar. Without it a deep, well-written, completely
    # off-topic question can ride depth and quality into the inbox.
    digest_min_topic_relevance: int = 40
    # Email delivery (prd.md §21). There is exactly one recipient, so it's a
    # deploy-time setting rather than profile state.
    resend_api_key: str = ""
    digest_recipient_email: str = ""
    email_from: str = ""
    # Public URL of the frontend, used for challenge links in the email.
    app_base_url: str = ""

    # A third bar, added after scoring real Stack Overflow data: topic + depth
    # + quality alone total 65, so a famous, well-written, on-topic question
    # cleared the threshold despite having 50 answers and an accepted one —
    # nothing left to solve, which is the whole point of the product. This
    # floor blocks questions whose opportunity to solve has already gone.
    digest_min_solve_opportunity: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def yutori_webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/webhooks/yutori?token={self.yutori_webhook_secret}"


settings = Settings()
