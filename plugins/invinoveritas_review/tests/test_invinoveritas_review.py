# -*- coding: utf-8 -*-
"""Live-shaped tests for InvinoveritasReviewPlugin -- no network calls, real HTTP mocking
via httpx.MockTransport (same pattern as invinoveritas's own AutoGen GovernedWorkbench
tests). Run: pytest plugins/invinoveritas_review/tests/test_invinoveritas_review.py -v
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from cpex.framework import GlobalContext, PluginConfig, PluginContext  # noqa: E402
from cpex.framework.hooks.tools import ToolPreInvokePayload  # noqa: E402

from plugins.invinoveritas_review.invinoveritas_review import InvinoveritasReviewPlugin  # noqa: E402


def _make_plugin(config: dict) -> InvinoveritasReviewPlugin:
    pc = PluginConfig(
        name="invinoveritas_review",
        kind="plugins.invinoveritas_review.invinoveritas_review.InvinoveritasReviewPlugin",
        version="0.1.0",
        author="babyblueviper1",
        hooks=["tool_pre_invoke"],
        tags=["safety", "review"],
        config=config,
    )
    return InvinoveritasReviewPlugin(pc)


def _ctx() -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id="req-test-1"))


def _patch_httpx(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)


@pytest.mark.asyncio
async def test_reject_blocks_by_default(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["artifact_type"] == "general"
        assert json.loads(body["artifact"])["tool_name"] == "delete_prod_db"
        return httpx.Response(200, json={"verdict": "reject", "confidence": 0.91, "summary": "Irreversible, no confirmation."})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    payload = ToolPreInvokePayload(name="delete_prod_db", args={"table": "users"})
    result = await plugin.tool_pre_invoke(payload, _ctx())

    assert result.continue_processing is False
    assert result.violation is not None
    assert result.violation.code == "IVV_REVIEW_REJECT"


@pytest.mark.asyncio
async def test_reject_does_not_block_in_advisory_mode(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"verdict": "reject", "confidence": 0.9, "summary": "risky"})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key", "block_on_reject": False})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="risky_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"]["verdict"] == "reject"


@pytest.mark.asyncio
async def test_approve_passes_through(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.97})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="read_file"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"]["verdict"] == "approve"


@pytest.mark.asyncio
async def test_fails_open_on_network_error(monkeypatch):
    def raise_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")

    _patch_httpx(monkeypatch, raise_handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"] == "unavailable"


@pytest.mark.asyncio
async def test_fails_open_on_malformed_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_a_verdict_field": True})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"] == "unavailable"


@pytest.mark.asyncio
async def test_no_api_key_fails_open_without_network_call(monkeypatch):
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"verdict": "reject"})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({})  # no api_key, no IVV_API_KEY env var assumed absent
    monkeypatch.delenv("IVV_API_KEY", raising=False)
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert called["n"] == 0  # never even attempted the call
