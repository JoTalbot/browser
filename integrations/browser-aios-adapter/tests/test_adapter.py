from octopus_browser_adapter.adapter import AIOSBrowserAdapter
from octopus_browser_adapter.config import AdapterSettings


class FakeBrowser:
    def __init__(self):
        self.actions = []

    def status(self):
        return [
            {
                "profile": "secondary",
                "connected": True,
                "pages": 1,
                "hosts": ["example.com"],
            }
        ]

    def screenshot(self, profile):
        self.actions.append(("screenshot", profile))
        return b"image"

    def navigate(self, profile, url, *, approved=False):
        self.actions.append(("navigate", profile, url, approved))

    def click(self, profile, selector, *, approved=False):
        self.actions.append(("click", profile, selector, approved))

    def fill(self, profile, selector, text, *, approved=False):
        self.actions.append(("fill", profile, selector, text, approved))


class FakeVision:
    def analyze_sync(self, image, mime_type, prompt):
        class Result:
            def as_dict(self):
                return {
                    "provider": "fake",
                    "model": "fake",
                    "text": "ok",
                    "latency_ms": 1,
                    "image_bytes": len(image),
                }

        return Result()


def test_adapter_exposes_safe_capabilities_and_routes_actions():
    browser = FakeBrowser()
    adapter = AIOSBrowserAdapter(
        AdapterSettings(), browser=browser, vision=FakeVision()
    )
    assert adapter.capabilities()["raw_profile_copy"] is False
    assert adapter.capabilities()["cookie_export"] is False
    assert adapter.observe("secondary")["vision"]["text"] == "ok"
    result = adapter.action(
        "secondary", "navigate", approved=True, url="https://example.com"
    )
    assert result["ok"] is True
    assert browser.actions[-1] == ("navigate", "secondary", "https://example.com", True)
