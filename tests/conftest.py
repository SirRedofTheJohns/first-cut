import pytest

from firstcut import config


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Tests never read the developer's .env: `get_settings()` would otherwise export its
    values (passwords, API keys) into the environment of the whole test process."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
