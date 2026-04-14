# Standard
from pathlib import Path

# Third-Party
import yaml

LINTING_WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "linting-full.yml"
MAKEFILE_PATH = Path(__file__).resolve().parents[2] / "Makefile"


def load_linting_workflow() -> dict:
    with LINTING_WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_linting_full_uses_patched_go_and_module_cache_paths():
    workflow = load_linting_workflow()
    steps = workflow["jobs"]["linting-full"]["steps"]

    setup_go_step = next(step for step in steps if step.get("name") == "Set up Go")
    assert setup_go_step["with"]["go-version"] == "1.26.2"
    assert setup_go_step["with"]["cache-dependency-path"].strip().splitlines() == [
        "a2a-agents/go/a2a-echo-agent/go.sum",
        "mcp-servers/go/benchmark-server/go.sum",
        "mcp-servers/go/fast-time-server/go.sum",
        "mcp-servers/go/slow-time-server/go.sum",
    ]


def test_linting_go_toolchain_is_patched_in_makefile():
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "LINT_GO_TOOLCHAIN ?= go1.26.2" in makefile
