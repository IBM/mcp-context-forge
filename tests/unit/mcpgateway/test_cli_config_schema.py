# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError


def test_config_schema_prints_json():
    """Schema command should emit valid JSON when no output file is given."""
    result = subprocess.run([sys.executable, "-m", "mcpgateway.cli", "--config-schema"], capture_output=True, text=True, check=True)

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "title" in data
    assert "properties" in data


def test_config_schema_writes_to_file(tmp_path: Path):
    """Schema command should write to a file when --output is given."""
    out_file = tmp_path / "schema.json"

    subprocess.run([sys.executable, "-m", "mcpgateway.cli", "--config-schema", str(out_file)], check=True)

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "title" in data
    assert "properties" in data


def test_insert_defaults_injects_app_host_port():
    """Defaults should be injected when no app/host/port provided."""
    # First-Party
    import mcpgateway.cli as cli

    args = cli._insert_defaults([])
    assert args[0] == cli.DEFAULT_APP
    assert "--host" in args
    assert "--port" in args


def test_insert_defaults_skips_host_port_for_uds():
    """Host/port defaults should be skipped when UDS is used."""
    # First-Party
    import mcpgateway.cli as cli

    args = cli._insert_defaults(["--uds", "/tmp/socket.sock"])
    assert args[0] == cli.DEFAULT_APP
    assert "--host" not in args
    assert "--port" not in args


def test_handle_validate_config_success(monkeypatch, capsys):
    """Validation success prints confirmation."""
    # First-Party
    import mcpgateway.cli as cli

    class DummySettings:
        def __init__(self, _env_file=None):
            self.path = _env_file

    monkeypatch.setattr(cli, "Settings", DummySettings)

    cli._handle_validate_config("custom.env")
    out = capsys.readouterr().out
    assert "Configuration in custom.env is valid" in out


def test_handle_validate_config_failure(monkeypatch, capsys):
    """Validation errors raise SystemExit and write to stderr."""
    # First-Party
    import mcpgateway.cli as cli

    class DummyModel:
        @staticmethod
        def build_error():
            class TempModel(BaseModel):
                field: int

            try:
                TempModel(field="bad")
            except ValidationError as exc:
                return exc
            raise AssertionError("ValidationError not raised")

    validation_error = DummyModel.build_error()

    def raise_error(*args, **kwargs):
        raise validation_error

    monkeypatch.setattr(cli, "Settings", raise_error)

    with pytest.raises(SystemExit):
        cli._handle_validate_config("bad.env")

    err = capsys.readouterr().err
    assert "Invalid configuration in bad.env" in err


def test_handle_config_schema_outputs_json(monkeypatch, capsys):
    """Schema helper prints JSON when no output is specified."""
    # First-Party
    import mcpgateway.cli as cli

    class DummySettings:
        @classmethod
        def model_json_schema(cls, mode="validation"):
            return {"title": "Dummy", "properties": {"x": {"type": "string"}}}

    monkeypatch.setattr(cli, "Settings", DummySettings)

    cli._handle_config_schema()
    data = json.loads(capsys.readouterr().out)
    assert data["title"] == "Dummy"


def test_handle_config_schema_writes_output(monkeypatch, tmp_path: Path):
    """Schema helper writes JSON to file when output is given."""
    # First-Party
    import mcpgateway.cli as cli

    class DummySettings:
        @classmethod
        def model_json_schema(cls, mode="validation"):
            return {"title": "Dummy", "properties": {"x": {"type": "string"}}}

    monkeypatch.setattr(cli, "Settings", DummySettings)

    out_file = tmp_path / "schema.json"
    cli._handle_config_schema(str(out_file))

    data = json.loads(out_file.read_text())
    assert data["title"] == "Dummy"


def test_handle_support_bundle_success(monkeypatch, tmp_path: Path, capsys):
    """Support bundle helper prints success message."""
    # First-Party
    import mcpgateway.cli as cli

    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(b"data")

    class DummyService:
        def __init__(self):
            self.called = False

        def generate_bundle(self, _config):
            self.called = True
            return bundle_path

    monkeypatch.setattr("mcpgateway.services.support_bundle_service.SupportBundleService", DummyService)

    cli._handle_support_bundle(output_dir=str(tmp_path), log_lines=10, include_logs=False, include_env=False, include_system=False)
    out = capsys.readouterr().out
    assert "Support bundle created" in out


def test_handle_support_bundle_failure(monkeypatch):
    """Support bundle helper raises SystemExit on failure."""
    # First-Party
    import mcpgateway.cli as cli

    class DummyService:
        def generate_bundle(self, _config):
            raise RuntimeError("boom")

    monkeypatch.setattr("mcpgateway.services.support_bundle_service.SupportBundleService", DummyService)

    with pytest.raises(SystemExit):
        cli._handle_support_bundle()


def test_main_support_bundle_parsing(monkeypatch):
    """CLI main should parse support bundle flags and invoke handler."""
    # First-Party
    import mcpgateway.cli as cli

    called = {}

    def fake_handle_support_bundle(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(cli, "_handle_support_bundle", fake_handle_support_bundle)
    monkeypatch.setattr(sys, "argv", ["mcpgateway", "--support-bundle", "--output-dir", "/tmp", "--log-lines", "42", "--no-logs", "--no-env"])

    cli.main()

    assert called["output_dir"] == "/tmp"
    assert called["log_lines"] == 42
    assert called["include_logs"] is False
    assert called["include_env"] is False
    assert called["include_system"] is True


def test_main_version_flag(monkeypatch, capsys):
    """CLI main should print version and exit."""
    # First-Party
    import mcpgateway.cli as cli

    monkeypatch.setattr(sys, "argv", ["mcpgateway", "--version"])
    cli.main()
    out = capsys.readouterr().out
    assert "mcpgateway" in out


def test_main_export_import_branch(monkeypatch):
    """CLI main should delegate to export/import subcommands."""
    # First-Party
    import mcpgateway.cli as cli

    mock_main = MagicMock()
    monkeypatch.setattr("mcpgateway.cli_export_import.main_with_subcommands", mock_main)
    monkeypatch.setattr(sys, "argv", ["mcpgateway", "export"])

    cli.main()
    mock_main.assert_called_once()


def test_main_calls_uvicorn(monkeypatch):
    """CLI main should invoke uvicorn with defaults."""
    # First-Party
    import mcpgateway.cli as cli

    called = {}

    def fake_main():
        called["argv"] = list(sys.argv)

    monkeypatch.setattr(cli.uvicorn, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["mcpgateway", "--reload"])

    cli.main()
    assert called["argv"][0] == "mcpgateway"
    assert cli.DEFAULT_APP in called["argv"]
