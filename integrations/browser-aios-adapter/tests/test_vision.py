import asyncio

import httpx
from octopus_browser_adapter.config import AdapterSettings
from octopus_browser_adapter.vision import VisionRouter

PNG = b"\x89PNG\r\n\x1a\nsynthetic"


def test_gemini_response_is_parsed_without_real_network():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers.get("x-goog-api-key") == "test-gemini"
        assert "key" not in request.url.query.decode()
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
        )

    router = VisionRouter(
        AdapterSettings(
            allow_external_vision=True,
            vision_provider="gemini",
            gemini_api_key="test-gemini",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(router.analyze(PNG))
    assert result.provider == "gemini"
    assert result.text == "OK"


def test_llm_balancer_uses_openai_compatible_image_request():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://llm.example/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer test-balancer"
        payload = request.read()
        assert b"data:image/png;base64," in payload
        assert b'"model":"auto"' in payload
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "from balancer"}}]}
        )

    router = VisionRouter(
        AdapterSettings(
            allow_external_vision=True,
            vision_provider="balancer",
            llm_balancer_url="https://llm.example/v1",
            llm_balancer_model="auto",
            llm_balancer_api_key="test-balancer",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(router.analyze(PNG))
    assert result.provider == "balancer"
    assert result.model == "auto"
    assert result.text == "from balancer"


def test_analyze_sync_works_inside_running_event_loop():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "threaded"}}]}
        )

    router = VisionRouter(
        AdapterSettings(
            allow_external_vision=True,
            vision_provider="balancer",
            llm_balancer_url="https://llm.example/v1",
        ),
        transport=httpx.MockTransport(handler),
    )

    async def run() -> str:
        return router.analyze_sync(PNG).text

    assert asyncio.run(run()) == "threaded"


def test_router_falls_back_to_groq_on_provider_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(503, json={"error": "synthetic"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "fallback"}}]}
        )

    router = VisionRouter(
        AdapterSettings(
            allow_external_vision=True,
            vision_provider="gemini",
            gemini_api_key="test-gemini",
            groq_api_key="test-groq",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(router.analyze(PNG))
    assert result.provider == "groq"
    assert result.text == "fallback"
    assert calls == ["generativelanguage.googleapis.com", "api.groq.com"]
