"""🧪 Тесты vision-движка: провайдеры, fusion, бюджеты, кэш, API (без сети и ключей)."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from octopus_browser import api as api_module
from octopus_browser.config import AppConfig
from octopus_browser.vision import (
    AdapterVisionProvider,
    MockVisionProvider,
    OpenAICompatVisionProvider,
    VisionBudgetExceeded,
    VisionEngine,
    VisionFrame,
    VisionProviderError,
    compose_context,
    render_prompt,
)

PNG_1PX_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def make_config(tmp_path, **overrides) -> AppConfig:
    cfg = AppConfig()
    cfg.data_dir = tmp_path
    cfg.ensure_dirs()
    cfg.adapter_url = ""
    cfg.vision_provider = "auto"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def make_engine(tmp_path, provider=None, **overrides) -> VisionEngine:
    return VisionEngine(make_config(tmp_path, **overrides), provider=provider)


@pytest.fixture()
def vision_client(tmp_path, monkeypatch):
    engine = make_engine(tmp_path, provider=MockVisionProvider({"click": '{"action":"click","target":"#ok","confidence":0.9}'}))
    monkeypatch.setattr(api_module, "vision_engine", engine)
    api_module.app.dependency_overrides[api_module.protected] = lambda: None
    yield TestClient(api_module.app), engine
    api_module.app.dependency_overrides.clear()


def test_prompt_registry_versions_and_unknown() -> None:
    version, text = render_prompt("describe", context="")
    assert version == "v1" and "скриншота" in text
    version, text = render_prompt("decide", goal="g", description="d", history="[]")
    assert version == "v1" and '"action"' in text and "Цель: g" in text
    with pytest.raises(ValueError, match="Неизвестный"):
        render_prompt("nope")


def test_frame_validation_and_cache_key() -> None:
    frame = VisionFrame(image_b64=PNG_1PX_B64)
    assert frame.image_bytes().startswith(b"\x89PNG")
    assert frame.cache_key("a") == VisionFrame(image_b64=PNG_1PX_B64).cache_key("a")
    assert frame.cache_key("a") != frame.cache_key("b")
    with pytest.raises(ValueError, match="base64"):
        VisionFrame(image_b64="!!!").image_bytes()


def test_compose_context_truncates() -> None:
    frame = VisionFrame(image_b64=PNG_1PX_B64, dom="D" * 9000, a11y="A" * 9000)
    context = compose_context(frame)
    assert len(context) < 9000 and "DOM" in context and "Accessibility" in context
    assert compose_context(VisionFrame(image_b64=PNG_1PX_B64)) == ""


def test_mock_provider_script_and_calls() -> None:
    provider = MockVisionProvider({"hello": "world"})
    assert provider.complete(b"img", "image/png", "say hello").text == "world"
    assert provider.complete(b"img", "image/png", "other").text == "mock-описание кадра"
    assert provider.calls == ["say hello", "other"]


def test_adapter_provider_paths() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/vision/analyze"
        return httpx.Response(200, json={"provider": "gemini", "model": "m", "text": "ok", "latency_ms": 3.0})

    provider = AdapterVisionProvider("http://adapter:9615", transport=httpx.MockTransport(ok))
    result = provider.complete(b"img", "image/png", "p")
    assert (result.provider, result.text) == ("gemini", "ok")

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "no keys"})

    with pytest.raises(VisionProviderError, match="HTTP 503"):
        AdapterVisionProvider("http://a", transport=httpx.MockTransport(down)).complete(b"i", "image/png", "p")

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": True})

    with pytest.raises(VisionProviderError, match="некорректный"):
        AdapterVisionProvider("http://a", transport=httpx.MockTransport(broken)).complete(b"i", "image/png", "p")


def test_openai_provider_ok() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "m1" and "image_url" in json.dumps(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "seen"}}]})

    provider = OpenAICompatVisionProvider("http://llm:9999/v1", "k", "m1", transport=httpx.MockTransport(ok))
    assert provider.complete(b"img", "image/png", "p").text == "seen"
    with pytest.raises(ValueError, match="VISION_API"):
        OpenAICompatVisionProvider("", "", "m")


def test_chain_failover_and_stats(tmp_path) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    def up(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "fine"}}]})

    engine = make_engine(
        tmp_path,
        provider=[
            AdapterVisionProvider("http://a", transport=httpx.MockTransport(down)),
            OpenAICompatVisionProvider("http://b", "k", "m", transport=httpx.MockTransport(up)),
        ],
    )
    result = engine.ask(VisionFrame(image_b64=PNG_1PX_B64), "prompt")
    assert result.provider == "openai" and result.text == "fine"
    stats = engine.stats()
    assert stats["calls_by_provider"] == {"openai": 1} and stats["chain"] == ["adapter", "openai"]


def test_empty_chain_stub_and_wait(tmp_path) -> None:
    engine = make_engine(tmp_path, provider=[])
    assert "заглуш" in engine.describe(PNG_1PX_B64)
    decision = engine.decide(PNG_1PX_B64, "goal", [])
    assert decision.action == "wait"


def test_budget_blocks_and_counts(tmp_path) -> None:
    engine = make_engine(tmp_path, provider=MockVisionProvider(), vision_max_calls_per_hour=2)
    frame = VisionFrame(image_b64=PNG_1PX_B64)
    engine.ask(frame, "one")
    engine.ask(frame, "two")
    with pytest.raises(VisionBudgetExceeded):
        engine.ask(frame, "three")
    assert "заглуш" in engine.describe_frame(VisionFrame(image_b64=PNG_1PX_B64))
    assert engine.stats()["budget"]["used_in_window"] == 2


def test_cache_hit_skips_provider(tmp_path) -> None:
    provider = MockVisionProvider()
    engine = make_engine(tmp_path, provider=provider)
    frame = VisionFrame(image_b64=PNG_1PX_B64)
    engine.ask(frame, "same")
    engine.ask(frame, "same")
    assert len(provider.calls) == 1 and engine.stats()["cache_hits"] == 1


def test_grounding_parse_clamp_and_failsafe(tmp_path) -> None:
    provider = MockVisionProvider({"find": '{"x": 1.5, "y": -0.2, "selector": "#a", "confidence": 2.0}'})
    engine = make_engine(tmp_path, provider=provider)
    grounding, degraded = engine.ground(VisionFrame(image_b64=PNG_1PX_B64), "find me")
    assert degraded is False
    assert (grounding.x, grounding.y, grounding.confidence) == (1.0, 0.0, 1.0)
    assert grounding.selector == "#a"
    provider.script["find"] = "not json"
    grounding, degraded = engine.ground(VisionFrame(image_b64=PNG_1PX_B64), "find me again")  # другой промпт — мимо кэша

    assert degraded is True and (grounding.x, grounding.y) == (0.0, 0.0)
    with pytest.raises(ValueError, match="target"):
        engine.ground(VisionFrame(image_b64=PNG_1PX_B64), "")


def test_decide_parses_action_and_rejects_unknown(tmp_path) -> None:
    provider = MockVisionProvider()
    engine = make_engine(tmp_path, provider=provider)
    provider.script["Цель"] = '{"action":"click","target":"#ok","text":"","reason":"r","confidence":0.9}'
    decision, degraded = engine.decide_frame(VisionFrame(image_b64=PNG_1PX_B64), "goal", ["h1"])
    assert degraded is False and decision.action == "click" and decision.confidence == 0.9
    provider.script["Цель"] = '{"action":"hack"}'
    decision, _ = engine.decide_frame(VisionFrame(image_b64=PNG_1PX_B64), "goal", [])
    assert decision.action == "wait"


def test_api_vision_analyze_modes(vision_client) -> None:
    client, _ = vision_client
    base = {"image_b64": PNG_1PX_B64, "mime_type": "image/png"}
    describe = client.post("/vision/analyze", json={**base, "mode": "describe", "prompt": "custom p"})
    assert describe.status_code == 200 and describe.json()["provider"] == "mock"
    registry = client.post("/vision/analyze", json={**base, "mode": "describe"})
    assert registry.status_code == 200 and registry.json()["prompt_version"] == "v1"
    decide = client.post("/vision/analyze", json={**base, "mode": "decide", "goal": "press ok"})
    assert decide.status_code == 200 and decide.json()["action"] == "click"
    ground = client.post("/vision/analyze", json={**base, "mode": "ground", "target": "button"})
    assert ground.status_code == 200 and "x" in ground.json()
    status = client.get("/vision/status")
    assert status.status_code == 200 and status.json()["chain"] == ["mock"]


def test_api_vision_validation(vision_client) -> None:
    client, _ = vision_client
    bad_mode = client.post("/vision/analyze", json={"image_b64": PNG_1PX_B64, "mode": "nope"})
    assert bad_mode.status_code == 422
    bad_b64 = client.post("/vision/analyze", json={"image_b64": "!!!"})
    assert bad_b64.status_code == 400
    bad_mime = client.post("/vision/analyze", json={"image_b64": PNG_1PX_B64, "mime_type": "image/gif"})
    assert bad_mime.status_code == 422
    no_target = client.post("/vision/analyze", json={"image_b64": PNG_1PX_B64, "mode": "ground"})
    assert no_target.status_code == 422


def test_api_vision_budget_429(tmp_path, monkeypatch) -> None:
    engine = make_engine(tmp_path, provider=MockVisionProvider(), vision_max_calls_per_hour=1)
    monkeypatch.setattr(api_module, "vision_engine", engine)
    api_module.app.dependency_overrides[api_module.protected] = lambda: None
    try:
        client = TestClient(api_module.app)
        first = client.post("/vision/analyze", json={"image_b64": PNG_1PX_B64, "prompt": "a"})
        assert first.status_code == 200
        second = client.post("/vision/analyze", json={"image_b64": PNG_1PX_B64, "prompt": "b"})
        assert second.status_code == 429
    finally:
        api_module.app.dependency_overrides.clear()
