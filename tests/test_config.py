from firstcut.config import Settings


def test_defaults_point_to_local_stack():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert settings.wp_url == "http://localhost:8080"
    assert settings.wp_app_password is None


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("WP_APP_PASSWORD", "abcd efgh")
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "groq"
    # Secrets are masked when printed but still readable on purpose.
    assert "abcd" not in repr(settings)
    assert settings.wp_app_password.get_secret_value() == "abcd efgh"
