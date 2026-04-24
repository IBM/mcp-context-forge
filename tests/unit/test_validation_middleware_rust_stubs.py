import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUB_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "__init__.pyi"
PY_TYPED_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "py.typed"
SUBMODULE_STUB_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "validation_middleware_rust" / "__init__.pyi"


def test_validation_middleware_rust_generates_packaged_stub():
    stub = STUB_PATH.read_text(encoding="utf-8")
    tree = ast.parse(stub)
    validator = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Validator")
    invalid_json_error = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "InvalidJsonError")
    json_depth_error = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "JsonDepthError")
    validate_json_bytes = next(node for node in validator.body if isinstance(node, ast.FunctionDef) and node.name == "validate_json_bytes")

    assert "class Validator:" in stub
    assert "InvalidJsonError" in ast.literal_eval(next(node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "__all__").value)
    assert "JsonDepthError" in ast.literal_eval(next(node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "__all__").value)
    assert "validate_json_data" not in ast.literal_eval(next(node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "__all__").value)
    assert ast.unparse(invalid_json_error.bases[0]) == "ValueError"
    assert ast.unparse(json_depth_error.bases[0]) == "ValueError"
    assert [arg.arg for arg in validate_json_bytes.args.args] == ["self", "raw_body"]
    assert ast.unparse(validate_json_bytes.returns) == "typing.Optional[tuple[builtins.str, builtins.str]]"
    assert "def validate_http_request" not in stub
    assert "def validate_resource_path" in stub


def test_validation_middleware_rust_marks_package_typed():
    assert PY_TYPED_PATH.exists()


def test_validation_middleware_rust_submodule_stub_exports_exceptions():
    stub = SUBMODULE_STUB_PATH.read_text(encoding="utf-8")
    tree = ast.parse(stub)
    exports = ast.literal_eval(next(node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "__all__").value)

    assert "InvalidJsonError" in exports
    assert "JsonDepthError" in exports
    assert "class InvalidJsonError(ValueError)" in stub
    assert "class JsonDepthError(ValueError)" in stub
