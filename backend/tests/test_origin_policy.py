from pathlib import Path
import sys


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from origin_policy import get_allowed_web_origins


def test_configured_origin_includes_www_alias_and_local_development():
    origins = get_allowed_web_origins(
        frontend_url="https://tapinx.in/",
        socket_allowed_origins="",
    )

    assert "https://tapinx.in" in origins
    assert "https://www.tapinx.in" in origins
    assert "http://localhost:5173" in origins


def test_www_origin_includes_bare_alias_without_duplicates():
    origins = get_allowed_web_origins(
        frontend_url="https://www.tapinx.in",
        socket_allowed_origins="https://www.tapinx.in,https://tapinx.in",
    )

    assert origins.count("https://tapinx.in") == 1
    assert origins.count("https://www.tapinx.in") == 1


def test_production_portal_is_allowed_when_deploy_domain_is_api_host():
    origins = get_allowed_web_origins(
        frontend_url="https://api.tapinx.in",
        socket_allowed_origins="https://api.tapinx.in",
    )

    assert "https://tapinx.in" in origins
    assert "https://www.tapinx.in" in origins
