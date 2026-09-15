# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/tool_shadow_detector/test_tool_shadow_detector.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for ToolShadowDetectorPlugin.
"""

# Standard
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPreInvokePayload
from plugins.tool_shadow_detector.tool_shadow_detector import ToolShadowDetectorPlugin, _levenshtein


def _make_plugin(**config_overrides):
    """Build a ToolShadowDetectorPlugin with optional config overrides."""
    return ToolShadowDetectorPlugin(
        PluginConfig(
            name="tsd",
            kind="plugins.tool_shadow_detector.tool_shadow_detector.ToolShadowDetectorPlugin",
            hooks=[ToolHookType.TOOL_PRE_INVOKE],
            config=config_overrides,
        )
    )


def _mock_db_rows(rows):
    """Return a MagicMock standing in for mcpgateway.db.get_db(), yielding a
    session whose db.execute(...).all() returns the given rows."""
    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = rows
    mock_session.close.return_value = None

    def _gen():
        yield mock_session

    return _gen


def test_levenshtein_basic():
    assert _levenshtein("get_user_role", "get_user_role") == 0
    assert _levenshtein("get_user_role", "get_user_roles") == 1
    assert _levenshtein("kitten", "sitting") == 3
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3


@pytest.mark.asyncio
async def test_flags_near_miss_name_from_different_gateway():
    """dvmcp-challenge5-get-user-roles (edit distance 1 from
    dvmcp-challenge5-get-user-role, different gateway) should be flagged."""
    plugin = _make_plugin(block_on_detection=False)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-shadow"))

    rows = [("dvmcp-challenge5-get-user-role", "gw-legit"), ("dvmcp-challenge1-get-user-info", "gw-legit")]
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge5-get-user-roles", args={}), ctx)

    assert res.violation is None  # default mode warns, does not block
    assert res.metadata is not None
    candidates = res.metadata["tool_shadow_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["name"] == "dvmcp-challenge5-get-user-role"
    assert candidates[0]["distance"] == 1


@pytest.mark.asyncio
async def test_blocks_when_block_on_detection_enabled():
    plugin = _make_plugin(block_on_detection=True)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-shadow"))

    rows = [("dvmcp-challenge5-get-user-role", "gw-legit")]
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge5-get-user-roles", args={}), ctx)

    assert res.continue_processing is False
    assert res.violation is not None
    assert res.violation.code == "TOOL_SHADOW_SUSPECTED"


@pytest.mark.asyncio
async def test_no_false_positive_on_unrelated_tool_names():
    plugin = _make_plugin()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-a"))

    rows = [("dvmcp-challenge1-get-user-info", "gw-b"), ("dvmcp-challenge3-file-manager", "gw-b")]
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge9-remote-access", args={}), ctx)

    assert res.violation is None
    assert res.metadata == {}


@pytest.mark.asyncio
async def test_flags_near_miss_name_on_same_gateway_by_default():
    """Realistic DVMCP Challenge 5 shape: the malicious shadow tool is
    registered on the SAME server as the legitimate one it impersonates
    (to blend in), not a different one. exempt_same_gateway defaults to
    False specifically so this case is caught by default."""
    plugin = _make_plugin()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-shadow"))

    rows = [("dvmcp-challenge5-get-user-role", "gw-shadow")]  # same gateway_id as the caller
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge5-get-user-roles", args={}), ctx)

    assert res.violation is None  # default mode warns, does not block
    candidates = res.metadata["tool_shadow_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["name"] == "dvmcp-challenge5-get-user-role"


@pytest.mark.asyncio
async def test_exempt_same_gateway_opt_in_suppresses_finding():
    """When explicitly opted in, same-gateway near-misses are suppressed --
    for deployments with verified, trusted multi-tool servers that
    intentionally use similar names."""
    plugin = _make_plugin(exempt_same_gateway=True)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-same"))

    rows = [("dvmcp-challenge5-get-user-role", "gw-same")]
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge5-get-user-roles", args={}), ctx)

    assert res.violation is None
    assert res.metadata == {}


@pytest.mark.asyncio
async def test_short_names_are_skipped():
    """Names shorter than min_name_length produce too many coincidental
    matches to be useful and should be skipped entirely."""
    plugin = _make_plugin(min_name_length=6)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-a"))

    rows = [("cp", "gw-b")]
    with patch("mcpgateway.db.get_db", _mock_db_rows(rows)):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="ls", args={}), ctx)

    assert res.violation is None
    assert res.metadata == {}


@pytest.mark.asyncio
async def test_registry_lookup_failure_does_not_block_invocation():
    """A DB error must never break normal tool invocation -- this plugin is
    a detector, not a hard dependency."""
    plugin = _make_plugin()
    ctx = PluginContext(global_context=GlobalContext(request_id="r1", server_id="gw-a"))

    def _broken_gen():
        raise RuntimeError("db unavailable")
        yield  # pragma: no cover -- unreachable, keeps this a generator

    with patch("mcpgateway.db.get_db", _broken_gen):
        res = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="dvmcp-challenge5-get-user-roles", args={}), ctx)

    assert res.continue_processing is True
    assert res.violation is None
