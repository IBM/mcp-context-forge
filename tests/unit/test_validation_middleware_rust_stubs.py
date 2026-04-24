import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUB_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "__init__.pyi"


def test_validation_middleware_rust_generates_packaged_stub():
    stub = STUB_PATH.read_text(encoding="utf-8")
    tree = ast.parse(stub)
    validator = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Validator")
    validate_http_request = next(node for node in validator.body if isinstance(node, ast.FunctionDef) and node.name == "validate_http_request")

    assert "class Validator:" in stub
    assert [arg.arg for arg in validate_http_request.args.args] == [
        "self",
        "parameters",
        "content_type",
        "raw_body",
        "skip_parameter_validation",
    ]
    assert [ast.unparse(default) for default in validate_http_request.args.defaults] == ["None", "False"]
    assert ast.unparse(validate_http_request.returns) == "typing.Optional[tuple[builtins.str, builtins.str]]"
    assert "def validate_resource_path" in stub
