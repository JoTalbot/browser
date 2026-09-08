from fastapi.testclient import TestClient
from octopus_browser_adapter.app import create_app
from octopus_browser_adapter.vision import VisionError


class FakeAdapter:
    def capabilities(self):
        return {"adapter": "test", "action_approval_required": True}

    def status(self):
        return {"profiles": [], "vision": {}}

    def aios_status(self):
        return {"ok": True, "service": "aios"}


def test_health_and_status_do_not_need_real_browser():
    client = TestClient(create_app(FakeAdapter()))
    assert client.get("/health").json()["adapter"] == "test"
    assert client.get("/status").status_code == 200
    assert client.get("/aios/status").json()["service"] == "aios"


class FakeVisionAdapter(FakeAdapter):
    def analyze_image(self, image_b64, mime_type="image/png", prompt="p"):
        if image_b64 == "bad":
            raise ValueError("image_b64 должен быть корректным base64")
        if image_b64 == "nokeys":
            raise VisionError("не настроен ни один vision API key")
        return {"provider": "mock", "model": "m", "text": "ok", "latency_ms": 1.0, "image_bytes": 3}


def test_vision_analyze_paths():
    client = TestClient(create_app(FakeVisionAdapter()))
    good = client.post("/vision/analyze", json={"image_b64": "aGk=", "mime_type": "image/png", "prompt": "p"})
    assert good.status_code == 200 and good.json()["text"] == "ok"
    bad = client.post("/vision/analyze", json={"image_b64": "bad"})
    assert bad.status_code == 400
    down = client.post("/vision/analyze", json={"image_b64": "nokeys"})
    assert down.status_code == 503
