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

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


settings = Settings()
