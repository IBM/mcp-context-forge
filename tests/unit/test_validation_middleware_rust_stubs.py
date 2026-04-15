from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUB_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "__init__.pyi"


def test_validation_middleware_rust_generates_packaged_stub():
    stub = STUB_PATH.read_text(encoding="utf-8")

    assert "class Validator:" in stub
    assert "def validate_http_request" in stub
    assert "def validate_resource_path" in stub
