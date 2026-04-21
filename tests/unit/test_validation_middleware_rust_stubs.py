from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUB_PATH = ROOT / "crates" / "validation_middleware_rust" / "python" / "validation_middleware_rust" / "__init__.pyi"


def test_validation_middleware_rust_generates_packaged_stub():
    stub = STUB_PATH.read_text(encoding="utf-8")
    normalized_stub = " ".join(stub.split())
    expected_signature = (
        "def validate_http_request( self, parameters: typing.Sequence[tuple[builtins.str, builtins.str]], "
        "content_type: builtins.str, raw_body: bytes | None = None, skip_parameter_validation: builtins.bool = False, "
        ") -> typing.Optional[tuple[builtins.str, builtins.str]]: ..."
    )

    assert "class Validator:" in stub
    assert expected_signature in normalized_stub
    assert "def validate_resource_path" in stub
