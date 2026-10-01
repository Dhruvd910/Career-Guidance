from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Career Guide API"
    environment: str = "development"

    database_url: str = "sqlite:///./data/app.db"

    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    cors_origins: list[str] = ["http://localhost:3000"]

    # LLM (OpenRouter — OpenAI-compatible chat completions + tool calling)
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # STT (Groq — Whisper)
    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # TTS (Cartesia)
    cartesia_api_key: str | None = None
    cartesia_voice_id: str | None = None
    cartesia_model: str = "sonic-3.6"
    cartesia_base_url: str = "https://api.cartesia.ai"

    @property
    def ai_configured(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
