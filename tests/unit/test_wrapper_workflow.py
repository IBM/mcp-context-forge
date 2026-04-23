from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "wrapper.yml"


def load_workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_wrapper_workflow_keeps_wrapper_specific_e2e_steps():
    workflow = load_workflow()
    steps = workflow["jobs"]["wrapper-e2e"]["steps"]

    build_step = next(step for step in steps if step.get("name") == "Build and test wrapper")
    assert "cargo build --release --features integration-test" in build_step["run"]
    assert "./target/release/wrapper_integration" in build_step["run"]


def test_wrapper_workflow_pins_actions():
    workflow = load_workflow()
    for step in workflow["jobs"]["wrapper-e2e"]["steps"]:
        uses = step.get("uses")
        if uses:
            _, _, ref = uses.partition("@")
            assert len(ref) == 40 and all(ch in "0123456789abcdef" for ch in ref), f"workflow action should be pinned to a full SHA, found {uses}"
