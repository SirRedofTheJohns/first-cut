"""Runtime configuration, read from environment variables (and `.env` in development)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "qwen3.5:9b"
    llm_temperature: float = 0.3

    # WordPress (local Docker instance by default)
    wp_url: str = "http://localhost:8080"
    wp_user: str = "admin"
    wp_app_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
