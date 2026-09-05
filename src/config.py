from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    log_level: str = "INFO"
    public_url: str = ""

    # Clerk auth (auth is disabled when clerk_jwks_url is empty)
    clerk_jwks_url: str = ""
    clerk_publishable_key: str = ""
    # Comma-separated emails allowed to use the dashboard; empty = any signed-in user
    allowed_emails: str = ""

    # Symmetric key for pgcrypto-encrypted integration secrets
    secrets_key: str = "dev-only-change-me"

    # Providers
    anthropic_api_key: str = ""
    default_llm_model: str = "claude-sonnet-5"
    devin_api_key: str = ""
    devin_api_base: str = "https://api.devin.ai/v1"
    railway_api_token: str = ""

    # Background scheduler (agent runs, integration syncs, uptime checks)
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300

    @property
    def auth_enabled(self) -> bool:
        return bool(self.clerk_jwks_url)

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}


settings = Settings()
