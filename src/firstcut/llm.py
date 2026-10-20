"""Provider-agnostic chat model factory.

Switching providers is configuration only: set LLM_PROVIDER and LLM_MODEL (plus that
provider's API key) and `init_chat_model` loads the matching LangChain integration.
An optional LLM_FALLBACK_PROVIDER / LLM_FALLBACK_MODEL takes over when the primary
provider errors (e.g. a free-tier 429).
"""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import InMemoryRateLimiter

from firstcut.config import Settings, get_settings

SUPPORTED_PROVIDERS = ("ollama", "groq", "google_genai", "huggingface", "anthropic", "openai")

# Groq's free tier allows 8K tokens/min and one call here uses ~2.5K, so ~3 calls/min.
# Without this, six parallel writers hit 429s that the SDK's own retries can't absorb.
_DEFAULT_RPS = {"groq": 0.05}


def get_chat_model(settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    return _build(
        settings, settings.llm_provider, settings.llm_model, settings.llm_requests_per_second
    )


def get_fallback_model(settings: Settings | None = None) -> BaseChatModel | None:
    settings = settings or get_settings()
    if not (settings.llm_fallback_provider and settings.llm_fallback_model):
        return None
    return _build(settings, settings.llm_fallback_provider, settings.llm_fallback_model)


def _build(settings: Settings, provider: str, model: str, rps: float = 0) -> BaseChatModel:
    """`rps` overrides the provider's default throttle; it only applies to the primary model,
    since each provider (and model) has its own free-tier limits."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM provider {provider!r}; expected one of {SUPPORTED_PROVIDERS}"
        )

    kwargs: dict[str, Any] = {"temperature": settings.llm_temperature}
    if provider == "ollama":
        # Thinking mode makes local models several times slower for little gain here.
        kwargs |= {"base_url": settings.ollama_base_url, "reasoning": False}
    if provider in ("groq", "google_genai"):
        # Free tiers answer bursts with 429 + Retry-After; let the SDK wait and retry.
        kwargs["max_retries"] = 6
    rps = rps or _DEFAULT_RPS.get(provider, 0)
    if rps > 0:
        kwargs["rate_limiter"] = InMemoryRateLimiter(requests_per_second=rps)
    return init_chat_model(model, model_provider=provider, **kwargs)
