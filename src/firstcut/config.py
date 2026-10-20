"""Runtime configuration, read from environment variables (and `.env` in development)."""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "hf.co/Qwen/Qwen3-8B-GGUF:Q8_0"
    llm_temperature: float = 0.3
    # Optional second provider used when the primary errors (e.g. Gemini 429 -> Groq).
    llm_fallback_provider: str | None = None
    llm_fallback_model: str | None = None
    # Client-side throttle for rate-limited free tiers (Groq, Gemini). 0 disables it.
    llm_requests_per_second: float = 0
    ollama_base_url: str = "http://localhost:11434"

    # Agent
    max_revisions: int = 2

    # WordPress (local Docker instance by default)
    wp_url: str = "http://localhost:8080"
    wp_user: str = "admin"
    wp_app_password: SecretStr | None = None

    # MCP server for WordPress tools. Empty: spawn it over stdio. Set it to use a running
    # server over streamable HTTP, e.g. http://localhost:8765/mcp
    mcp_wordpress_url: str | None = None

    # Figma (brand styles) and Google Docs (briefs)
    figma_token: SecretStr | None = None
    figma_cache_dir: str = ".cache/figma"
    figma_cache_hours: float = 24
    google_application_credentials: str | None = None

    # API
    webhook_secret: SecretStr | None = None
    webhook_tolerance_seconds: int = 300
    checkpoint_db: str = "data/checkpoints.sqlite"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # pydantic-settings reads .env into Settings but doesn't export it, while LangChain
    # integrations read provider keys (GOOGLE_API_KEY, GROQ_API_KEY...) from os.environ.
    # Real environment variables (e.g. Space secrets) still win: override=False.
    load_dotenv(".env", override=False)
    return Settings()
