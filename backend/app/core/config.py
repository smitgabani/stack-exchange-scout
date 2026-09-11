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


settings = Settings()
