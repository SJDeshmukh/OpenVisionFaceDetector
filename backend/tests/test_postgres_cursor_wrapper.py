import ast
from pathlib import Path


def _wrapper_class():
    source_path = Path(__file__).resolve().parents[1] / "db_factory.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(
        item for item in module.body
        if isinstance(item, ast.ClassDef) and item.name == "PostgresCursorWrapper"
    )
    namespace = {"re": __import__("re"), "logger": __import__("logging").getLogger(__name__)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace["PostgresCursorWrapper"]


def test_description_is_forwarded_from_psycopg_cursor():
    class FakeCursor:
        description = [("id",), ("name",)]

    wrapped = _wrapper_class()(FakeCursor())

    assert wrapped.description == [("id",), ("name",)]


class FakeInsertCursor:
    description = None

    def __init__(self, rows):
        self.rows = list(rows)
        self.executed_sql = None
        self.rowcount = 1

    def execute(self, sql, params):
        self.executed_sql = sql

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def test_explicit_returning_result_is_left_for_the_caller():
    raw = FakeInsertCursor([(41, 7)])
    wrapped = _wrapper_class()(raw)

    wrapped.execute(
        "INSERT INTO faces(name) VALUES (?) RETURNING id, display_id",
        ("Sudhanshu",),
    )

    assert wrapped.fetchone() == (41, 7)
    assert wrapped.lastrowid is None


def test_implicit_returning_is_consumed_for_lastrowid_compatibility():
    raw = FakeInsertCursor([(41,)])
    wrapped = _wrapper_class()(raw)

    wrapped.execute("INSERT INTO faces(name) VALUES (?)", ("Sudhanshu",))

    assert raw.executed_sql.endswith(" RETURNING id")
    assert wrapped.lastrowid == 41
