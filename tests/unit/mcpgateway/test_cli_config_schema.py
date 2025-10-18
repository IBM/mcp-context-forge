# -*- coding: utf-8 -*-
import json
import subprocess
from pathlib import Path


def test_config_schema_prints_json():
    """Schema command should emit valid JSON when no output file is given."""
    result = subprocess.run(["python", "-m", "mcpgateway.cli", "--config-schema"], capture_output=True, text=True, check=True)

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "title" in data
    assert "properties" in data


def test_config_schema_writes_to_file(tmp_path: Path):
    """Schema command should write to a file when --output is given."""
    out_file = tmp_path / "schema.json"

    subprocess.run(["python", "-m", "mcpgateway.cli", "--config-schema", str(out_file)], check=True)

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "title" in data
    assert "properties" in data
