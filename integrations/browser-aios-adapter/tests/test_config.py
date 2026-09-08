from octopus_browser_adapter.config import AdapterSettings


def test_public_status_does_not_expose_keys():
    settings = AdapterSettings(
        gemini_api_key="gemini-secret", groq_api_key="groq-secret"
    )
    text = repr(settings.public_status())
    assert "secret" not in text
    assert settings.public_status()["configured_vision_providers"] == ["gemini", "groq"]


def test_balancer_status_exposes_only_configuration_state():
    settings = AdapterSettings(
        llm_balancer_url="http://127.0.0.1:13014/v1",
        llm_balancer_model="auto",
        llm_balancer_api_key="balancer-secret",
    )
    status = settings.public_status()
    assert status["llm_balancer_configured"] is True
    assert "balancer" in status["configured_vision_providers"]
    assert status["vision_models"]["balancer"] == "auto"
    assert "secret" not in repr(status)


def test_from_env_uses_server_arena_key_as_balancer_fallback(monkeypatch):
    monkeypatch.setenv("OCTOPUS_BROWSER_LLM_BALANCER_URL", "https://arena.example/v1")
    monkeypatch.setenv("ARENA_API_KEY", "server-arena-secret")
    monkeypatch.delenv("OCTOPUS_BROWSER_LLM_BALANCER_API_KEY", raising=False)
    settings = AdapterSettings.from_env()
    assert settings.llm_balancer_api_key == "server-arena-secret"


def test_from_env_uses_groq_key_when_balancer_key_is_missing(monkeypatch):
    monkeypatch.setenv(
        "OCTOPUS_BROWSER_LLM_BALANCER_URL", "https://api.groq.com/openai/v1"
    )
    monkeypatch.delenv("OCTOPUS_BROWSER_LLM_BALANCER_API_KEY", raising=False)
    monkeypatch.delenv("ARENA_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "server-groq-secret")
    settings = AdapterSettings.from_env()
    assert settings.llm_balancer_api_key == "server-groq-secret"


def test_from_env_prefers_matching_groq_key_over_stale_arena_key(monkeypatch):
    monkeypatch.setenv(
        "OCTOPUS_BROWSER_LLM_BALANCER_URL", "https://api.groq.com/openai/v1"
    )
    monkeypatch.delenv("OCTOPUS_BROWSER_LLM_BALANCER_API_KEY", raising=False)
    monkeypatch.setenv("ARENA_API_KEY", "stale-arena-secret")
    monkeypatch.setenv("GROQ_API_KEY", "server-groq-secret")
    settings = AdapterSettings.from_env()
    assert settings.llm_balancer_api_key == "server-groq-secret"


def test_profile_endpoints_are_named_not_file_paths():
    settings = AdapterSettings()
    assert settings.endpoint("primary").cdp_url.endswith(":9222")
    assert settings.endpoint("secondary").cdp_url.endswith(":9224")
    assert "/profile" not in settings.endpoint("secondary").cdp_url
