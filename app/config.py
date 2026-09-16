from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All runtime configuration lives here, loaded from environment variables
    (or a local .env file). Nothing else in the app should call os.environ
    directly — add new settings here instead.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Discord ---
    discord_token: str = ""
    command_prefix: str = "!"
    enable_bot: bool = True

    # --- Database (PostgreSQL default in prod, SQLite async fallback for dev/test) ---
    database_url: str = "sqlite+aiosqlite:///./mico.db"

    # --- FastAPI Web Server ---
    enable_api: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- AI provider selection ---
    # "gemini" today; "groq" / "openai" / "openrouter" are supported.
    # Change this (or the env var) and nothing else in the codebase needs to change.
    ai_provider: str = "gemini"

    # --- Gemini ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    # Tried in order if the primary model returns a server-side error (503
    # overloaded, 500, etc). Comma-separated in .env, e.g.:
    # GEMINI_FALLBACK_MODELS=gemini-1.5-flash,gemini-1.5-flash-8b
    gemini_fallback_models: str = "gemini-1.5-flash,gemini-1.5-flash-8b"

    # --- Groq (OpenAI-compatible) ---
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_fallback_models: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- OpenAI-compatible (OpenAI / OpenRouter) — for later ---
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_fallback_models: str = ""
    openai_base_url: str | None = None  # set for OpenRouter, leave unset for OpenAI

    # --- GitHub Integration ---
    github_token: str | None = None
    github_default_user: str | None = None

    # --- Agent behavior ---
    max_history_messages: int = 20

    # --- Misc ---
    log_level: str = "INFO"

    @staticmethod
    def _build_chain(primary: str, fallback_csv: str) -> list[str]:
        """Primary model followed by fallbacks, de-duplicated, in order."""
        fallbacks = [m.strip() for m in fallback_csv.split(",") if m.strip()]
        chain = [primary, *fallbacks]
        seen: set[str] = set()
        return [m for m in chain if not (m in seen or seen.add(m))]

    @property
    def gemini_model_chain(self) -> list[str]:
        return self._build_chain(self.gemini_model, self.gemini_fallback_models)

    @property
    def groq_model_chain(self) -> list[str]:
        return self._build_chain(self.groq_model, self.groq_fallback_models)

    @property
    def openai_model_chain(self) -> list[str]:
        return self._build_chain(self.openai_model, self.openai_fallback_models)


@lru_cache
def get_settings() -> Settings:
    return Settings()
