import pytest
from octopus_browser_adapter.browser import (
    ActionApprovalRequired,
    CDPBrowserAdapter,
    ProfileUnavailable,
)
from octopus_browser_adapter.config import AdapterSettings


def test_actions_require_approval_before_cdp_connection():
    browser = CDPBrowserAdapter(AdapterSettings())
    with pytest.raises(ActionApprovalRequired):
        browser.navigate("secondary", "https://example.com")


def test_invalid_profile_is_rejected_without_cdp_connection():
    browser = CDPBrowserAdapter(AdapterSettings())
    with pytest.raises(ProfileUnavailable):
        browser.screenshot("copied-profile")
