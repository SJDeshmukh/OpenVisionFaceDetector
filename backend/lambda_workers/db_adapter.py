"""Small PostgreSQL compatibility layer for DB-only Lambda workers.

The application services use SQLite-style ``?`` placeholders.  Production
PostgreSQL normally gets the same compatibility from ``db_factory``, but that
module also imports the Flask application and image stack.  Keeping this
adapter here prevents those dependencies from entering the report Lambda.
"""

from __future__ import annotations

import os


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, statement, params=None):
        self._cursor.execute(statement.replace("?", "%s"), params or ())
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class Connection:
    _is_pg = True

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        from psycopg2.extras import DictCursor

        return Cursor(self._connection.cursor(cursor_factory=DictCursor))

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_db_connection():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg2

    raw = psycopg2.connect(
        database_url,
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5")),
        application_name="tapinx-report-preparation-lambda",
    )
    return Connection(raw)
