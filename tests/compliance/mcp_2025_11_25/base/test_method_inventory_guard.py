# -*- coding: utf-8 -*-
"""Schema method inventory guard for MCP 2025-11-25."""

# Standard
from pathlib import Path
from typing import Set

# Third-Party
from mcp import types
from pydantic import BaseModel
import pytest
import yaml


def _manifest_path() -> Path:
    return Path(__file__).resolve().parents[1] / "manifest" / "schema_methods.yaml"


def _collect_method_literals_from_mcp_types() -> Set[str]:
    methods: Set[str] = set()
    for obj in vars(types).values():
        if not isinstance(obj, type):
            continue
        if not issubclass(obj, BaseModel):
            continue
        fields = getattr(obj, "model_fields", {})
        if "method" not in fields:
            continue
        default = fields["method"].default
        if isinstance(default, str):
            methods.add(default)
    return methods


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_base
@pytest.mark.mcp_required
def test_latest_protocol_version_constant():
    assert types.LATEST_PROTOCOL_VERSION == "2025-11-25"


@pytest.mark.mcp20251125
@pytest.mark.mcp_core
@pytest.mark.mcp_base
@pytest.mark.mcp_required
def test_manifest_method_inventory_matches_mcp_types():
    with _manifest_path().open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)

    assert manifest["protocol_version"] == "2025-11-25"
    expected_methods = set(manifest["methods"])
    discovered_methods = _collect_method_literals_from_mcp_types()
    assert discovered_methods == expected_methods
