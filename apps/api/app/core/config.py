from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Career Guide API"
    environment: str = "development"

    database_url: str = "sqlite:///./data/app.db"
    # PostgreSQL (Phase 2): where scripts/sqlite_to_postgres.py copies to, and the throwaway
    # database the `postgres`-marked tests use. DATABASE_URL is switched to it once copied.
    postgres_url: str | None = None
    postgres_test_url: str | None = None

    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    cors_origins: list[str] = ["http://localhost:3000"]

    # Which implementation each AI service uses (see app/providers/registry.py).
    llm_provider: str = "openrouter"  # openrouter | openai_compatible
    stt_provider: str = "groq"  # groq | none
    tts_provider: str = "cartesia"  # cartesia | none

    # LLM via OpenRouter — OpenAI-compatible chat completions + tool calling
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # LLM via any other OpenAI-compatible server (OpenAI, llama.cpp, Ollama…), when
    # llm_provider=openai_compatible. A local server usually needs no key.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    # STT (Groq — Whisper)
    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # TTS (Cartesia)
    cartesia_api_key: str | None = None
    cartesia_voice_id: str | None = None
    cartesia_model: str = "sonic-3.6"
    cartesia_base_url: str = "https://api.cartesia.ai"
    tts_sample_rate: int = 44100  # of the streamed PCM sent to the device


@lru_cache
def get_settings() -> Settings:
    return Settings()
