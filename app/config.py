from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic / Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-4-5-20251101"
    claude_vision_model: str = "claude-opus-4-5-20251101"

    # App
    app_name: str = "Huddlebiz"
    app_env: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./data/huddlebiz.db"

    # Session
    session_ttl_days: int = 30

    # Backend AI Integration
    backend_api_url: str = "https://api.huddlebiz.com"
    ai_service_token: str = ""


settings = Settings()
