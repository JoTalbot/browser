from fastapi.testclient import TestClient
from octopus_browser_adapter.app import create_app


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
