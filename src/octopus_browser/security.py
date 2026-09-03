"""🔐 Authentication, egress policy and secret-safe security primitives."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class EgressTarget:
    """Resolved destination used by callers that need a stable network policy."""

    url: str
    host: str
    addresses: tuple[str, ...]


def require_api_key(
    x_api_key: str | None = Header(default=None),
    expected_key: str | None = None,
) -> None:
    """Require the configured API key without re-reading environment state."""
    if not expected_key:
        raise HTTPException(503, "API authentication is not configured")
    if x_api_key != expected_key:
        raise HTTPException(401, "Invalid API key")


def resolve_safe_target(value: str, allowed_hosts: list[str] | None = None) -> EgressTarget:
    """Resolve and validate an outbound target before browser/network use."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url должен быть абсолютным http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("URL с учётными данными запрещён")
    host = parsed.hostname.rstrip(".").lower()
    normalized_allowed = [h.rstrip(".").lower() for h in (allowed_hosts or [])]
    if normalized_allowed and not any(
        host == item or host.endswith("." + item) for item in normalized_allowed
    ):
        raise ValueError("host не разрешён политикой egress")
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("host не разрешён или не разрешается") from exc
    addresses = tuple(sorted({info[4][0] for info in infos}))
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError("частные/локальные адреса запрещены")
    return EgressTarget(url=value, host=host, addresses=addresses)


def validate_external_url(value: str, allowed_hosts: list[str] | None = None) -> str:
    """Backward-compatible URL validator returning the original URL."""
    return resolve_safe_target(value, allowed_hosts).url
