"""Shared HTTP and Socket.IO origin policy."""

import os
from urllib.parse import urlsplit, urlunsplit


_LOCAL_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

# The production portal is served by CloudFront while the API also has a
# separate hostname.  DEPLOY_DOMAIN can therefore describe the API host and
# cannot be the only source of browser origins accepted by Socket.IO.
_TAPINX_WEB_ORIGINS = (
    "https://tapinx.in",
    "https://www.tapinx.in",
)


def _split_origins(value):
    return [item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()]


def _www_alias(origin):
    """Return the bare/www companion for a configured web origin."""
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not hostname:
            return None
        if hostname in {"localhost", "127.0.0.1"} or ":" in hostname:
            return None

        alias_host = hostname[4:] if hostname.startswith("www.") else f"www.{hostname}"
        port = f":{parsed.port}" if parsed.port else ""
        return urlunsplit((parsed.scheme, f"{alias_host}{port}", "", "", ""))
    except (ValueError, TypeError):
        return None


def get_allowed_web_origins(frontend_url=None, socket_allowed_origins=None):
    """Return normalized, exact origins accepted by HTTP and Socket.IO."""
    configured = _split_origins(
        socket_allowed_origins
        if socket_allowed_origins is not None
        else os.environ.get("SOCKET_ALLOWED_ORIGINS", "")
    )
    configured.extend(
        _split_origins(
            frontend_url
            if frontend_url is not None
            else os.environ.get("FRONTEND_URL", "http://localhost:5173")
        )
    )

    origins = []
    for origin in [*configured, *_TAPINX_WEB_ORIGINS, *_LOCAL_ORIGINS]:
        for candidate in (origin, _www_alias(origin)):
            if candidate and candidate not in origins:
                origins.append(candidate)
    return origins
