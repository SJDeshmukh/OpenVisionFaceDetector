import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

import pytest


DB_FACTORY_PATH = Path(__file__).resolve().parents[1] / "db_factory.py"


def _load_db_factory(monkeypatch):
    database = types.ModuleType("database")
    models = types.ModuleType("database.models")
    models.db = object()
    database.models = models

    psycopg2 = types.ModuleType("psycopg2")
    pool_module = types.ModuleType("psycopg2.pool")
    pool_module.ThreadedConnectionPool = object
    extras = types.ModuleType("psycopg2.extras")
    extras.DictCursor = object
    extensions = types.ModuleType("psycopg2.extensions")
    extensions.TRANSACTION_STATUS_IDLE = 0
    extensions.TRANSACTION_STATUS_INERROR = 3
    psycopg2.pool = pool_module
    psycopg2.extras = extras
    psycopg2.extensions = extensions

    monkeypatch.setitem(sys.modules, "database", database)
    monkeypatch.setitem(sys.modules, "database.models", models)
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", pool_module)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    monkeypatch.setitem(sys.modules, "psycopg2.extensions", extensions)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    name = "db_factory_pool_saturation_test"
    spec = importlib.util.spec_from_file_location(name, DB_FACTORY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ExhaustedPool:
    def getconn(self):
        raise RuntimeError("connection pool exhausted")


def test_pool_exhaustion_never_falls_back_to_sqlite(monkeypatch):
    db_factory = _load_db_factory(monkeypatch)
    monkeypatch.setenv("DB_POOL_WAIT_SECONDS", "0")
    monkeypatch.setattr(db_factory, "get_pg_pool", lambda: _ExhaustedPool())

    def unexpected_sqlite(*args, **kwargs):
        raise AssertionError("SQLite must not be used for transient pool saturation")

    monkeypatch.setattr(db_factory.sqlite3, "connect", unexpected_sqlite)

    with pytest.raises(db_factory.PostgresPoolTimeoutError):
        db_factory.get_db_connection()

    assert db_factory.is_fallback_mode() is False


def test_busy_pool_retries_until_a_connection_is_available(monkeypatch):
    db_factory = _load_db_factory(monkeypatch)
    expected_connection = object()

    class Pool:
        attempts = 0

        def getconn(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("connection pool exhausted")
            return expected_connection

    pool = Pool()
    acquired = db_factory._acquire_pg_connection(pool, wait_seconds=0.01)

    assert acquired is expected_connection
    assert pool.attempts == 2


def test_actual_postgres_failure_keeps_existing_sqlite_failover(monkeypatch, tmp_path):
    db_factory = _load_db_factory(monkeypatch)

    class FailedPool:
        def getconn(self):
            raise RuntimeError("database server is unavailable")

    fallback_path = tmp_path / "fallback.sqlite"
    monkeypatch.setattr(db_factory, "DB_PATH", str(fallback_path))
    monkeypatch.setattr(db_factory, "get_pg_pool", lambda: FailedPool())

    conn = db_factory.get_db_connection()
    try:
        assert isinstance(conn.conn, sqlite3.Connection)
        assert db_factory.is_fallback_mode() is True
    finally:
        conn.close()
