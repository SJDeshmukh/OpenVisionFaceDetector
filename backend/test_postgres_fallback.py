import importlib
import os
import sqlite3
import sys
import tempfile
import unittest


class TestPostgresFallback(unittest.TestCase):
    def test_invalid_database_url_falls_back_to_sqlite(self):
        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        try:
            os.environ["DB_PATH"] = db_path
            os.environ["DATABASE_URL"] = "postgresql://invalid:invalid@127.0.0.1:65432/doesnotexist"

            if "app" in sys.modules:
                del sys.modules["app"]
            app = importlib.import_module("app")

            self.assertFalse(app.postgres_available())
            conn = app.get_db_connection()
            try:
                self.assertIsInstance(conn, sqlite3.Connection)
            finally:
                conn.close()
        finally:
            try:
                os.close(db_fd)
            except Exception:
                pass
            try:
                os.remove(db_path)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
