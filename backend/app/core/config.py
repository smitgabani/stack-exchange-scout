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
    # can change (tdd.md §4.3a). Drives the M9 spend estimate.
    yutori_run_cost_usd: float = 0.35

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def yutori_webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/webhooks/yutori?token={self.yutori_webhook_secret}"


settings = Settings()
