import httpx
from octopus_browser_adapter.bridge import AIOSBridgeClient


def test_aios_status_client_uses_local_contract_without_secrets():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/aios/status"
        return httpx.Response(200, json={"ok": True, "service": "aios"})

    client = AIOSBridgeClient(
        "http://127.0.0.1:9600", transport=httpx.MockTransport(handler)
    )
    assert client.status() == {"ok": True, "service": "aios"}
