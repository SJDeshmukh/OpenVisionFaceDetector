import importlib.util
import sys
import types
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


class PostgresPoolTimeoutError(TimeoutError):
    pass


class PostgresUnavailableError(ConnectionError):
    pass


class Response(dict):
    def __init__(self, payload):
        super().__init__(payload)
        self.headers = {}


def _install_common_stubs(monkeypatch):
    flask = types.ModuleType("flask")
    flask.request = types.SimpleNamespace(
        headers={"Authorization": "Bearer test-token"},
        cookies={},
    )
    flask.g = types.SimpleNamespace()
    flask.jsonify = lambda payload: Response(payload)
    monkeypatch.setitem(sys.modules, "flask", flask)

    db_factory = types.ModuleType("db_factory")
    db_factory.PostgresPoolTimeoutError = PostgresPoolTimeoutError
    db_factory.PostgresUnavailableError = PostgresUnavailableError
    db_factory.get_db_connection = lambda: (_ for _ in ()).throw(
        PostgresPoolTimeoutError("pool busy")
    )
    monkeypatch.setitem(sys.modules, "db_factory", db_factory)

    werkzeug = types.ModuleType("werkzeug")
    exceptions = types.ModuleType("werkzeug.exceptions")

    class HTTPException(Exception):
        code = 500
        description = "HTTP error"
        name = "HTTP Error"

    exceptions.HTTPException = HTTPException
    werkzeug.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "werkzeug", werkzeug)
    monkeypatch.setitem(sys.modules, "werkzeug.exceptions", exceptions)
    return flask


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authentication_returns_retryable_503_when_pool_stays_busy(monkeypatch):
    _install_common_stubs(monkeypatch)

    itsdangerous = types.ModuleType("itsdangerous")
    itsdangerous.URLSafeTimedSerializer = object
    monkeypatch.setitem(sys.modules, "itsdangerous", itsdangerous)

    werkzeug = types.ModuleType("werkzeug")
    security = types.ModuleType("werkzeug.security")
    security.generate_password_hash = lambda value: value
    security.check_password_hash = lambda stored, value: stored == value
    werkzeug.security = security
    monkeypatch.setitem(sys.modules, "werkzeug", werkzeug)
    monkeypatch.setitem(sys.modules, "werkzeug.security", security)

    utils = types.ModuleType("utils")
    utils.parse_db_date = lambda value: value
    monkeypatch.setitem(sys.modules, "utils", utils)

    services = types.ModuleType("services")
    identity = types.ModuleType("services.login_identity_service")
    identity.is_valid_login_email = lambda value: True
    identity.login_email_from_profile = lambda value: value
    identity.normalize_login_email = lambda value: value
    services.login_identity_service = identity
    monkeypatch.setitem(sys.modules, "services", services)
    monkeypatch.setitem(sys.modules, "services.login_identity_service", identity)

    auth_service = _load_module(
        "auth_service_database_busy_test",
        BACKEND / "services" / "auth_service.py",
    )
    auth_service.verify_token = lambda token: {
        "username": "user@example.com",
        "role": "vendor_admin",
        "platform": "web",
    }

    vendor_id, error = auth_service.authenticate_vendor_access()
    response, status = error

    assert vendor_id is None
    assert status == 503
    assert response["code"] == "DATABASE_BUSY"
    assert response["retryable"] is True
    assert response.headers["Retry-After"] == "1"

    auth_service.get_db_connection = lambda: (_ for _ in ()).throw(
        PostgresUnavailableError("database down")
    )
    vendor_id, unavailable_error = auth_service.authenticate_vendor_access()
    unavailable_response, unavailable_status = unavailable_error

    assert vendor_id is None
    assert unavailable_status == 503
    assert unavailable_response["code"] == "DATABASE_UNAVAILABLE"
    assert unavailable_response["retryable"] is True


def test_global_handler_returns_retryable_503(monkeypatch):
    _install_common_stubs(monkeypatch)

    error_handlers = _load_module(
        "database_busy_error_handler_test",
        BACKEND / "middleware" / "error_handlers.py",
    )

    class App:
        handlers = {}

        def errorhandler(self, error_type):
            def register(function):
                self.handlers[error_type] = function
                return function

            return register

    app = App()
    error_handlers.register_error_handlers(app)
    response, status = app.handlers[PostgresPoolTimeoutError](
        PostgresPoolTimeoutError("pool busy")
    )

    assert status == 503
    assert response["code"] == "DATABASE_BUSY"
    assert response["retryable"] is True
    assert response.headers["Retry-After"] == "1"

    unavailable_response, unavailable_status = app.handlers[PostgresUnavailableError](
        PostgresUnavailableError("database down")
    )
    assert unavailable_status == 503
    assert unavailable_response["code"] == "DATABASE_UNAVAILABLE"
    assert unavailable_response["retryable"] is True
