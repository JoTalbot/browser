"""🔐 API authentication and conservative outbound URL policy."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import Header, HTTPException


def require_api_key(
    x_api_key: str | None = Header(default=None),
    expected_key: str | None = None,
) -> None:
    """Require the configured API key without re-reading environment state."""
    if not expected_key:
        raise HTTPException(503, "API authentication is not configured")
    if x_api_key != expected_key:
        raise HTTPException(401, "Invalid API key")


def validate_external_url(value: str, allowed_hosts: list[str] | None = None) -> str:
    """Validate URL syntax, host policy, and resolved address safety."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url должен быть абсолютным http/https URL")
    host = parsed.hostname.rstrip(".").lower()
    if parsed.username or parsed.password:
        raise ValueError("URL с учётными данными запрещён")
    if allowed_hosts and not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        raise ValueError("host не разрешён политикой egress")
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("host не разрешён или не разрешается") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("частные/локальные адреса запрещены")
    return value
