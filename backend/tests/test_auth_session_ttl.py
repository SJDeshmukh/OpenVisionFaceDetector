import sys
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

pytest.importorskip("itsdangerous")
from services import auth_service


def test_web_tokens_are_verified_with_one_hour_ttl(monkeypatch):
    ages = []

    class Serializer:
        def loads(self, _token, max_age):
            ages.append(max_age)
            return {"username": "user@example.com", "role": "user", "platform": "web"}

    monkeypatch.setattr(auth_service, "_serializer", Serializer())
    assert auth_service.WEB_TOKEN_TTL == 3600
    assert auth_service.verify_token("signed-token")["platform"] == "web"
    assert ages == [auth_service.PERSISTENT_TOKEN_TTL, 3600]
