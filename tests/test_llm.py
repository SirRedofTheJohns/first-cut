import pytest
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from firstcut.config import Settings
from firstcut.llm import get_chat_model


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_ollama_is_the_default_and_disables_thinking():
    llm = get_chat_model(settings())
    assert isinstance(llm, ChatOllama)
    assert llm.reasoning is False


def test_provider_is_switched_by_config_only(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm = get_chat_model(
        settings(llm_provider="groq", llm_model="openai/gpt-oss-20b", llm_requests_per_second=0.5)
    )
    assert isinstance(llm, ChatGroq)
    assert llm.model_name == "openai/gpt-oss-20b"
    assert llm.rate_limiter is not None


def test_unknown_provider_fails_fast():
    with pytest.raises(ValueError, match="Unsupported"):
        get_chat_model(settings(llm_provider="skynet"))
