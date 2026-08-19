# -*- coding: utf-8 -*-
"""Location: ./tests/unit/test_docker_entrypoint.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Direct unit tests for container release contracts and docker-entrypoint.sh.
"""

# Future
from __future__ import annotations

# Standard
from pathlib import Path
import stat
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker-entrypoint.sh"
INTRANET_RELEASE_DEFAULTS = {
    "SSRF_PROTECTION_ENABLED": "true",
    "SSRF_ALLOW_LOCALHOST": "true",
    "SSRF_ALLOW_PRIVATE_NETWORKS": "true",
    "SSRF_DNS_FAIL_CLOSED": "true",
    "MCPGATEWAY_GRPC_ENABLED": "true",
}


def _read_active_env(path: Path) -> dict[str, str]:
    """Return uncommented key/value assignments from an env file."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_app_root(tmp_path: Path) -> Path:
    app_root = tmp_path / "app"
    (app_root / ".venv" / "bin").mkdir(parents=True)
    (app_root / "plugins").mkdir()
    return app_root


def _run_install_plugin_requirements(app_root: Path, requirements_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = f"""
set -euo pipefail
export CONTEXTFORGE_TEST_ONLY_SOURCE=true
export APP_ROOT="{app_root}"
source "{ENTRYPOINT}"
export RELOAD_PLUGIN_REQUIREMENTS_TXT=true
export PLUGIN_REQUIREMENTS_TXT_PATH="{requirements_path or app_root / 'plugins' / 'requirements.txt'}"
export PLUGIN_REQUIREMENTS_RETRY_DELAY_SECONDS=0
install_plugin_requirements
"""
    return subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def _run_entrypoint_function(app_root: Path, function_name: str, exports: dict[str, str]) -> subprocess.CompletedProcess[str]:
    export_lines = "\n".join(f'export {key}="{value}"' for key, value in exports.items())
    command = f"""
set -euo pipefail
export CONTEXTFORGE_TEST_ONLY_SOURCE=true
export APP_ROOT="{app_root}"
source "{ENTRYPOINT}"
{export_lines}
{function_name}
"""
    return subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def test_intranet_release_defaults_are_baked_into_release_artifacts() -> None:
    """Release packaging and deployment artifacts must retain intranet access."""
    containerfile = (REPO_ROOT / "Containerfile").read_text(encoding="utf-8")
    runtime_stage = containerfile.split("FROM ${UBI_MINIMAL} AS runtime", maxsplit=1)[1]
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    embedded_compose = (REPO_ROOT / "docker-compose-embedded.yml").read_text(encoding="utf-8")
    chart_values = (REPO_ROOT / "charts" / "mcp-stack" / "values.yaml").read_text(encoding="utf-8")
    example_env = _read_active_env(REPO_ROOT / ".env.example")

    for name, expected in INTRANET_RELEASE_DEFAULTS.items():
        assert f"{name}={expected}" in runtime_stage
        assert f"- {name}=${{{name}:-{expected}}}" in compose
        assert f"- {name}=${{{name}:-{expected}}}" in embedded_compose
        assert f'    {name}: "{expected}"' in chart_values
        assert example_env.get(name) == expected


def test_print_mcp_runtime_mode_warns_when_rust_enabled(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)

    result = _run_entrypoint_function(
        app_root,
        "print_mcp_runtime_mode",
        {
            "EXPERIMENTAL_RUST_MCP_RUNTIME_ENABLED": "true",
            "EXPERIMENTAL_RUST_MCP_RUNTIME_MANAGED": "true",
        },
    )

    assert result.returncode == 0
    assert "Rust MCP runtime sidecar is deprecated as of 2026-06-11 and will sunset on 2026-07-07" in result.stdout


def test_install_plugin_requirements_refuses_path_outside_app_root(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    outside_requirements = tmp_path / "outside.txt"
    outside_requirements.write_text("cpex-rate-limiter==0.0.3\n", encoding="utf-8")

    result = _run_install_plugin_requirements(app_root, outside_requirements)

    assert result.returncode == 1
    assert "must resolve under" in result.stdout


def test_install_plugin_requirements_refuses_missing_file(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    missing_requirements = app_root / "plugins" / "missing.txt"

    result = _run_install_plugin_requirements(app_root, missing_requirements)

    assert result.returncode == 1
    assert "not found" in result.stdout


def test_install_plugin_requirements_retries_three_times_then_fails(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    requirements = app_root / "plugins" / "requirements.txt"
    requirements.write_text("cpex-rate-limiter==0.0.3\n", encoding="utf-8")
    attempts_file = tmp_path / "attempts.txt"
    _write_executable(
        app_root / ".venv" / "bin" / "pip",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo attempt >> "{attempts_file}"
exit 1
""",
    )

    result = _run_install_plugin_requirements(app_root, requirements)

    assert result.returncode == 1
    assert attempts_file.read_text(encoding="utf-8").count("attempt") == 3
    assert "failed after 3 attempts" in result.stdout


def test_install_plugin_requirements_rejects_invalid_retry_delay(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    requirements = app_root / "plugins" / "requirements.txt"
    requirements.write_text("cpex-rate-limiter==0.0.3\n", encoding="utf-8")
    _write_executable(
        app_root / ".venv" / "bin" / "pip",
        """#!/usr/bin/env bash
exit 0
""",
    )
    command = f"""
set -euo pipefail
export CONTEXTFORGE_TEST_ONLY_SOURCE=true
export APP_ROOT="{app_root}"
source "{ENTRYPOINT}"
export RELOAD_PLUGIN_REQUIREMENTS_TXT=true
export PLUGIN_REQUIREMENTS_TXT_PATH="{requirements}"
export PLUGIN_REQUIREMENTS_RETRY_DELAY_SECONDS="not-a-number"
install_plugin_requirements
"""

    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0
    assert "is not a non-negative number; falling back to 2s" in result.stdout


def test_install_plugin_requirements_succeeds_after_retry(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    requirements = app_root / "plugins" / "requirements.txt"
    requirements.write_text("# comment\n\ncpex-rate-limiter==0.0.3\n", encoding="utf-8")
    attempts_file = tmp_path / "attempts.txt"
    _write_executable(
        app_root / ".venv" / "bin" / "pip",
        f"""#!/usr/bin/env bash
set -euo pipefail
count=0
if [[ -f "{attempts_file}" ]]; then
    count=$(wc -l < "{attempts_file}")
fi
echo attempt >> "{attempts_file}"
if [[ "$count" -lt 1 ]]; then
    exit 1
fi
exit 0
""",
    )

    result = _run_install_plugin_requirements(app_root, requirements)

    assert result.returncode == 0
    assert attempts_file.read_text(encoding="utf-8").count("attempt") == 2
    assert "Installing 1 plugin package requirement" in result.stdout
    assert "attempt 1/3 failed" in result.stdout


def test_install_plugin_requirements_skips_when_reload_disabled(tmp_path: Path) -> None:
    app_root = _make_app_root(tmp_path)
    marker = tmp_path / "pip-called.txt"
    _write_executable(
        app_root / ".venv" / "bin" / "pip",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo called > "{marker}"
exit 0
""",
    )
    command = f"""
set -euo pipefail
export CONTEXTFORGE_TEST_ONLY_SOURCE=true
export APP_ROOT="{app_root}"
source "{ENTRYPOINT}"
export RELOAD_PLUGIN_REQUIREMENTS_TXT=false
install_plugin_requirements
"""

    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0
    assert not marker.exists()
    assert result.stdout == ""
