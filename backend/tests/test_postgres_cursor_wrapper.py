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
