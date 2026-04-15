from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "license-check.yml"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_license_check_runs_for_rust_repositories_and_inputs():
    workflow = load_workflow()
    on_block = workflow.get("on", workflow.get(True))

    expected_paths = {
        "pyproject.toml",
        "Cargo.toml",
        "Cargo.lock",
        "crates/**",
        "mcp-servers/rust/**",
        "package.json",
        "package-lock.json",
        "license-policy.toml",
        "scripts/license_checker.py",
        ".github/workflows/license-check.yml",
    }

    assert expected_paths.issubset(set(on_block["push"]["paths"]))
    assert expected_paths.issubset(set(on_block["pull_request"]["paths"]))
