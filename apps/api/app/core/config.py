from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Career Guide API"
    environment: str = "development"

    database_url: str = "sqlite:///./data/app.db"
    # PostgreSQL (Phase 2): where scripts/sqlite_to_postgres.py copies to, and the throwaway
    # database the `postgres`-marked tests use. DATABASE_URL is switched to it once copied.
    postgres_url: str | None = None
    postgres_test_url: str | None = None

    jwt_secret_key: str = DEV_JWT_SECRET  # refused in production (get_settings)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    cors_origins: list[str] = ["http://localhost:3000"]

    # Which implementation each AI service uses (see app/providers/registry.py).
    llm_provider: str = "openrouter"  # openrouter | openai_compatible
    stt_provider: str = "groq"  # groq | none
    tts_provider: str = "cartesia"  # cartesia | none

    # LLM via OpenRouter — OpenAI-compatible chat completions + tool calling
    openrouter_api_key: str | None = None
    # The live model. On MAYA's benchmark (2026-10-05) gpt-6-luna called the right tool every time,
    # never guessed a student's gender and kept replies short, at gpt-4o-mini's cost per turn.
    openrouter_model: str = "openai/gpt-6-luna"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # "deny": OpenRouter only routes to providers that neither store nor train on what's sent — students
    # are mostly minors. (Free models whose provider trains on inputs are then unavailable, by design.)
    openrouter_data_collection: str = "deny"
    # Tried in order when the model above is unavailable or rate-limited (e.g. a free model's daily cap):
    # OPENROUTER_FALLBACK_MODELS=["openai/gpt-oss-120b"]
    openrouter_fallback_models: list[str] = ["openai/gpt-oss-120b"]

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

    # The background model: it writes session notes into memory and reads how the student seems.
    # Nobody waits for it, so it's chosen for quality per rupee, not speed. On a test session
    # (2026-10-05) gpt-oss-120b caught all 9 things claude-haiku-4.5 did — the constraints, worries
    # and next step that gpt-4o-mini partly missed — for 1/16 of haiku's cost. Empty = the live model.
    memory_model: str = "openai/gpt-oss-120b"
    # Phase 6: the model that reads official documents, and where college knowledge lives — the
    # OKF bundle (canonical, its own git repo) and the raw documents it was read from.
    extraction_model: str = "google/gemini-2.5-flash"
    okf_bundle_path: str = "./data/okf"
    source_store_path: str = "./data/sources"
    # A conversation with no new turn for this long is over: its memory is written.
    session_idle_minutes: int = 10
    memory_sweeper: bool = True  # off in tests, which must never touch the real database

    # Encryption of students' words and MAYA's notes (app/core/crypto.py). Without a key here, one is
    # made at memory_key_path on first use — back it up, separately from the database.
    memory_encryption_key: str | None = None
    memory_key_path: str = "./data/memory.key"

    # Logs: "json" lines (spec §29) or "text".
    log_format: str = "json"

    # Embeddings for MAYA's memory, computed on the Pi (app/providers/embedding.py)
    embedding_provider: str = "local_e5"  # local_e5 | none
    embedding_model_dir: str = "models/multilingual-e5-small"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and (settings.jwt_secret_key == DEV_JWT_SECRET or len(settings.jwt_secret_key) < 32):
        raise RuntimeError("JWT_SECRET_KEY must be set to a long random value in production "
                           "(python3 -c \"import secrets; print(secrets.token_hex(32))\")")
    return settings
