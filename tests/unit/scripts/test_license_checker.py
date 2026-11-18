# -*- coding: utf-8 -*-
"""Location: ./tests/unit/scripts/test_license_checker.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for Python license checks without a Go toolchain.
"""

# Standard
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

# Third-Party
import pytest

# Local
from scripts import license_checker


@pytest.mark.parametrize("summary_only", [False, True])
@pytest.mark.parametrize(
    "project_license, dependency_license, expected_scope",
    [("Apache-2.0", "MIT", None), ("GPL-3.0", "MIT", "pyproject"), ("Apache-2.0", "GPL-3.0", "pip")],
)
def test_python_license_checks_without_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], summary_only: bool, project_license: str, dependency_license: str, expected_scope: str | None
) -> None:
    """Check Python licenses and both report formats without Go tools."""
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "example"\nlicense = "{project_license}"\n', encoding="utf-8")
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(license_checker, "ROOT", tmp_path)
    arguments = ["license_checker.py", "--config", str(tmp_path / "policy.toml"), "--report-json", str(report_path)]
    if summary_only:
        arguments.append("--summary-only")
    monkeypatch.setattr("sys.argv", arguments)
    command = ["pip-licenses", "--format=csv"]
    result = subprocess.CompletedProcess(command, 0, stdout=f'"Name","Version","License"\n"dependency","1.0","{dependency_license}"\n', stderr="")

    with patch("scripts.license_checker.shutil.which", side_effect=lambda name: "/bin/pip-licenses" if name == "pip-licenses" else None) as which:
        with patch.object(license_checker, "_run_command", return_value=result) as run:
            assert license_checker.main() == (1 if expected_scope else 0)

    which.assert_called_once_with("pip-licenses")
    run.assert_called_once_with(command, tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report["stats"]) == {"pyproject", "pip", "pip-subvenv"}
    assert report["stats"]["pyproject"] == {"manifests": 1, "evaluated": 1}
    assert report["stats"]["pip"]["dependencies"] == 1
    assert report["summary"]["ok"] is (expected_scope is None)
    assert [finding["scope"] for finding in report["findings"]] == ([expected_scope] if expected_scope else [])
    output = capsys.readouterr().out
    assert "# GO" not in output
    assert "go modules" not in output.lower()
