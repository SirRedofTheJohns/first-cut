"""Provider-agnostic chat model factory.

Switching providers is configuration only: set LLM_PROVIDER and LLM_MODEL (plus that
provider's API key) and `init_chat_model` loads the matching LangChain integration.
"""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter

from firstcut.config import Settings, get_settings

SUPPORTED_PROVIDERS = ("ollama", "groq", "google_genai", "huggingface", "anthropic", "openai")


def get_chat_model(settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    provider = settings.llm_provider
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM_PROVIDER {provider!r}; expected one of {SUPPORTED_PROVIDERS}"
        )

    kwargs: dict[str, Any] = {"temperature": settings.llm_temperature}
    if provider == "ollama":
        # Thinking mode makes local models several times slower for little gain here.
        kwargs |= {"base_url": settings.ollama_base_url, "reasoning": False}
    if settings.llm_requests_per_second > 0:
        kwargs["rate_limiter"] = InMemoryRateLimiter(
            requests_per_second=settings.llm_requests_per_second
        )

    return init_chat_model(settings.llm_model, model_provider=provider, **kwargs)
