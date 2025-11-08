# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/external_clamav/test_clamav_remote.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for ClamAVRemotePlugin (direct import, eicar_only mode).
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
)
from mcpgateway.common.models import ResourceContent
from mcpgateway.common.models import Message, PromptResult, Role, TextContent

from plugins.external.clamav_server.clamav_plugin import ClamAVRemotePlugin


EICAR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def _mk_plugin(block_on_positive: bool = True) -> ClamAVRemotePlugin:
    cfg = PluginConfig(
        name="clamav",
        kind="plugins.external.clamav_server.clamav_plugin.ClamAVRemotePlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH, ResourceHookType.RESOURCE_POST_FETCH],
        config={
            "mode": "eicar_only",
            "block_on_positive": block_on_positive,
        },
    )
    return ClamAVRemotePlugin(cfg)


@pytest.mark.asyncio
async def test_resource_pre_fetch_blocks_on_eicar(tmp_path):
    p = tmp_path / "eicar.txt"
    p.write_text(EICAR)
    plugin = _mk_plugin(True)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    payload = ResourcePreFetchPayload(uri=f"file://{p}")
    res = await plugin.resource_pre_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "CLAMAV_INFECTED"


@pytest.mark.asyncio
async def test_resource_post_fetch_blocks_on_eicar_text():
    plugin = _mk_plugin(True)
    ctx = PluginContext(global_context=GlobalContext(request_id="r2"))
    rc = ResourceContent(type="resource", id="123", uri="test://mem", mime_type="text/plain", text=EICAR)
    payload = ResourcePostFetchPayload(uri="test://mem", content=rc)
    res = await plugin.resource_post_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "CLAMAV_INFECTED"


@pytest.mark.asyncio
async def test_non_blocking_mode_reports_metadata(tmp_path):
    p = tmp_path / "eicar2.txt"
    p.write_text(EICAR)
    plugin = _mk_plugin(False)
    ctx = PluginContext(global_context=GlobalContext(request_id="r3"))
    payload = ResourcePreFetchPayload(uri=f"file://{p}")
    res = await plugin.resource_pre_fetch(payload, ctx)
    assert res.violation is None
    assert res.metadata is not None
    assert res.metadata.get("clamav", {}).get("infected") is True


@pytest.mark.asyncio
async def test_prompt_post_fetch_blocks_on_eicar_text():
    plugin = _mk_plugin(True)
    from mcpgateway.plugins.framework import PromptPosthookPayload

    pr = PromptResult(
        messages=[
            Message(
                role="assistant",
                content=TextContent(type="text", text=EICAR),
            )
        ]
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r4"))
    payload = PromptPosthookPayload(prompt_id="p", result=pr)
    res = await plugin.prompt_post_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "CLAMAV_INFECTED"


@pytest.mark.asyncio
async def test_tool_post_invoke_blocks_on_eicar_string():
    plugin = _mk_plugin(True)
    from mcpgateway.plugins.framework import ToolPostInvokePayload

    ctx = PluginContext(global_context=GlobalContext(request_id="r5"))
    payload = ToolPostInvokePayload(name="t", result={"text": EICAR})
    res = await plugin.tool_post_invoke(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "CLAMAV_INFECTED"


@pytest.mark.asyncio
async def test_health_stats_counters():
    # Non-blocking to allow multiple attempts to pass and count
    plugin = _mk_plugin(False)
    ctx = PluginContext(global_context=GlobalContext(request_id="r6"))

    # 1) resource_post_fetch with EICAR -> attempted +1, infected +1
    rc = ResourceContent(type="resource", id="123", uri="test://mem", mime_type="text/plain", text=EICAR)
    payload_r = ResourcePostFetchPayload(uri="test://mem", content=rc)
    await plugin.resource_post_fetch(payload_r, ctx)

    # 2) prompt_post_fetch with EICAR -> attempted +1, infected +1 (total attempted=2, infected=2)
    from mcpgateway.plugins.framework import PromptPosthookPayload

    pr = PromptResult(
        messages=[
            Message(
                role="assistant",
                content=TextContent(type="text", text=EICAR),
            )
        ]
    )
    payload_p = PromptPosthookPayload(prompt_id="p", result=pr)
    await plugin.prompt_post_fetch(payload_p, ctx)

    # 3) tool_post_invoke with one EICAR and one clean string -> attempted +2, infected +1
    from mcpgateway.plugins.framework import ToolPostInvokePayload

    payload_t = ToolPostInvokePayload(name="t", result={"a": EICAR, "b": "clean"})
    await plugin.tool_post_invoke(payload_t, ctx)

    h = plugin.health()
    stats = h.get("stats", {})
    assert stats.get("attempted") == 4
    assert stats.get("infected") == 3
    assert stats.get("blocked") == 0
    assert stats.get("errors") == 0
