# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/virus_total_checker/test_virus_total_checker.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for VirusTotalURLCheckerPlugin with stubbed client.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    ResourceHookType,
    ToolHookType,
    ResourcePreFetchPayload,
)

from plugins.virus_total_checker.virus_total_checker import VirusTotalURLCheckerPlugin
from mcpgateway.common.models import Message, PromptResult, TextContent


class _Resp:
    def __init__(self, status_code=200, data=None, headers=None):
        self.status_code = status_code
        self._data = data or {}
        self.headers = headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 404:
            raise RuntimeError(f"HTTP {self.status_code}")


class _StubClient:
    def __init__(self, routes):
        self.routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        fn = self.routes.get(("GET", url))
        if callable(fn):
            return fn()
        return _Resp(404)

    async def post(self, url, **kwargs):
        fn = self.routes.get(("POST", url))
        if callable(fn):
            return fn()
        return _Resp(404)


@pytest.mark.asyncio
async def test_url_block_on_malicious(tmp_path, monkeypatch):
    # Prepare plugin with a stubbed client factory
    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "enabled": True,
            "check_url": True,
            "check_domain": False,
            "check_ip": False,
            "block_on_verdicts": ["malicious"],
            "min_malicious": 1,
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    # Stub URL info response with malicious count
    url = "https://evil.example/path"
    from base64 import urlsafe_b64encode

    url_id = urlsafe_b64encode(url.encode()).decode().strip("=")
    base = "https://www.virustotal.com/api/v3"
    routes = {
        ("GET", f"{base}/urls/{url_id}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 2, "harmless": 80}
                    }
                }
            },
        )
    }

    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    payload = ResourcePreFetchPayload(uri=url)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.resource_pre_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "VT_URL_BLOCK"


@pytest.mark.asyncio
async def test_local_allow_and_deny_overrides():
    url = "https://override.example/x"
    from base64 import urlsafe_b64encode
    url_id = urlsafe_b64encode(url.encode()).decode().strip("=")
    base = "https://www.virustotal.com/api/v3"

    # VT would report malicious, but local allow should bypass
    routes = {
        ("GET", f"{base}/urls/{url_id}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 1, "harmless": 0}
                    }
                }
            },
        )
    }

    # Allow override
    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        config={
            "enabled": True,
            "scan_tool_outputs": True,
            "allow_url_patterns": ["override\\.example"],
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)
    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"
    from mcpgateway.plugins.framework import ToolPostInvokePayload
    payload = ToolPostInvokePayload(name="writer", result=f"See {url}")
    ctx = PluginContext(global_context=GlobalContext(request_id="r7"))
    res = await plugin.tool_post_invoke(payload, ctx)
    # Should not block because of local allow; also shouldn't call VT for this URL
    assert res.violation is None

    # Deny override
    cfg2 = PluginConfig(
        name="vt2",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        config={
            "enabled": True,
            "scan_tool_outputs": True,
            "deny_url_patterns": ["override\\.example"],
        },
    )
    plugin2 = VirusTotalURLCheckerPlugin(cfg2)
    plugin2._client_factory = lambda c, h: _StubClient({})  # no VT needed
    res2 = await plugin2.tool_post_invoke(payload, ctx)
    assert res2.violation is not None
    assert res2.violation.code == "VT_LOCAL_DENY"


@pytest.mark.asyncio
async def test_override_precedence_allow_over_deny_vs_deny_over_allow():
    url = "https://both.example/path/malware"
    # allow pattern will match domain, deny pattern matches path

    # allow_over_deny: allow wins, skip VT
    cfg_allow = PluginConfig(
        name="vt-allow",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        config={
            "enabled": True,
            "scan_tool_outputs": True,
            "allow_url_patterns": ["both\\.example"],
            "deny_url_patterns": ["malware"],
            "override_precedence": "allow_over_deny",
        },
    )
    plugin_allow = VirusTotalURLCheckerPlugin(cfg_allow)
    plugin_allow._client_factory = lambda c, h: _StubClient({})  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"
    from mcpgateway.plugins.framework import ToolPostInvokePayload
    payload = ToolPostInvokePayload(name="writer", result=f"visit {url}")
    ctx = PluginContext(global_context=GlobalContext(request_id="r8"))
    res_allow = await plugin_allow.tool_post_invoke(payload, ctx)
    assert res_allow.violation is None

    # deny_over_allow: deny wins, block immediately
    cfg_deny = PluginConfig(
        name="vt-deny",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        config={
            "enabled": True,
            "scan_tool_outputs": True,
            "allow_url_patterns": ["both\\.example"],
            "deny_url_patterns": ["malware"],
            "override_precedence": "deny_over_allow",
        },
    )
    plugin_deny = VirusTotalURLCheckerPlugin(cfg_deny)
    plugin_deny._client_factory = lambda c, h: _StubClient({})  # type: ignore
    res_deny = await plugin_deny.tool_post_invoke(payload, ctx)
    assert res_deny.violation is not None
    assert res_deny.violation.code == "VT_LOCAL_DENY"


@pytest.mark.asyncio
async def test_prompt_scan_blocks_on_url():
    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[PromptHookType.PROMPT_POST_FETCH],
        config={
            "enabled": True,
            "scan_prompt_outputs": True,
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    url = "https://bad.example/"
    from base64 import urlsafe_b64encode
    url_id = urlsafe_b64encode(url.encode()).decode().strip("=")
    base = "https://www.virustotal.com/api/v3"
    routes = {
        ("GET", f"{base}/urls/{url_id}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 1, "harmless": 10}
                    }
                }
            },
        )
    }
    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    pr = PromptResult(messages=[Message(role="assistant", content=TextContent(type="text", text=f"see {url}"))])
    from mcpgateway.plugins.framework import PromptPosthookPayload
    payload = PromptPosthookPayload(prompt_id="p", result=pr)
    ctx = PluginContext(global_context=GlobalContext(request_id="r5"))
    res = await plugin.prompt_post_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "VT_URL_BLOCK"


@pytest.mark.asyncio
async def test_resource_scan_blocks_on_url():
    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ResourceHookType.RESOURCE_POST_FETCH],
        config={
            "enabled": True,
            "scan_resource_contents": True,
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    url = "https://bad2.example/"
    from base64 import urlsafe_b64encode
    url_id = urlsafe_b64encode(url.encode()).decode().strip("=")
    base = "https://www.virustotal.com/api/v3"
    routes = {
        ("GET", f"{base}/urls/{url_id}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 1, "harmless": 10}
                    }
                }
            },
        )
    }
    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    from mcpgateway.common.models import ResourceContent
    rc = ResourceContent(type="resource", id="345",uri="test://x", mime_type="text/plain", text=f"{url} is fishy")
    from mcpgateway.plugins.framework import ResourcePostFetchPayload
    payload = ResourcePostFetchPayload(uri="test://x", content=rc)
    ctx = PluginContext(global_context=GlobalContext(request_id="r6"))
    res = await plugin.resource_post_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "VT_URL_BLOCK"


@pytest.mark.asyncio
async def test_file_hash_lookup_blocks(tmp_path, monkeypatch):
    # Create a temp file
    p = tmp_path / "sample.bin"
    p.write_bytes(b"hello world")
    sha256 = __import__("hashlib").sha256(b"hello world").hexdigest()

    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "enabled": True,
            "enable_file_checks": True,
            "upload_if_unknown": False,
            "block_on_verdicts": ["malicious"],
            "min_malicious": 1,
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    base = "https://www.virustotal.com/api/v3"
    routes = {
        ("GET", f"{base}/files/{sha256}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 1, "harmless": 10}
                    }
                }
            },
        )
    }
    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    uri = f"file://{p}"
    payload = ResourcePreFetchPayload(uri=uri)
    ctx = PluginContext(global_context=GlobalContext(request_id="r2"))
    res = await plugin.resource_pre_fetch(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "VT_FILE_BLOCK"


@pytest.mark.asyncio
async def test_unknown_file_then_upload_wait_allows_when_clean(tmp_path):
    p = tmp_path / "clean.bin"
    p.write_bytes(b"abc123")
    sha256 = __import__("hashlib").sha256(b"abc123").hexdigest()

    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
        config={
            "enabled": True,
            "enable_file_checks": True,
            "upload_if_unknown": True,
            "wait_for_analysis": True,
            "block_on_verdicts": ["malicious", "suspicious"],
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    base = "https://www.virustotal.com/api/v3"
    analysis_id = "analysis-123"
    routes = {
        # initial hash lookup -> unknown
        ("GET", f"{base}/files/{sha256}"): lambda: _Resp(404),
        # upload
        ("POST", f"{base}/files"): lambda: _Resp(200, data={"data": {"id": analysis_id}}),
        # poll analyses -> completed
        ("GET", f"{base}/analyses/{analysis_id}"): lambda: _Resp(
            200, data={"data": {"attributes": {"status": "completed"}}}
        ),
        # re-check hash -> clean
        ("GET", f"{base}/files/{sha256}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"malicious": 0, "suspicious": 0, "harmless": 15}
                    }
                }
            },
        ),
    }

    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    uri = f"file://{p}"
    payload = ResourcePreFetchPayload(uri=uri)
    ctx = PluginContext(global_context=GlobalContext(request_id="r3"))
    res = await plugin.resource_pre_fetch(payload, ctx)
    assert res.violation is None
    assert res.metadata is not None and "virustotal" in res.metadata
@pytest.mark.asyncio
async def test_tool_output_url_block_and_ratio():
    cfg = PluginConfig(
        name="vt",
        kind="plugins.virus_total_checker.virus_total_checker.VirusTotalURLCheckerPlugin",
        hooks=[ToolHookType.TOOL_POST_INVOKE],
        config={
            "enabled": True,
            "scan_tool_outputs": True,
            "min_harmless_ratio": 0.9,  # enforce high harmless ratio
        },
    )
    plugin = VirusTotalURLCheckerPlugin(cfg)

    # Prepare two URLs: one insufficient harmless ratio
    url = "https://maybe.example/thing"
    from base64 import urlsafe_b64encode
    url_id = urlsafe_b64encode(url.encode()).decode().strip("=")
    base = "https://www.virustotal.com/api/v3"

    # harmless = 5, undetected = 50 -> harmless_ratio = 5/55 < 0.9 => block
    routes = {
        ("GET", f"{base}/urls/{url_id}"): lambda: _Resp(
            200,
            data={
                "data": {
                    "attributes": {
                        "last_analysis_stats": {"harmless": 5, "undetected": 50}
                    }
                }
            },
        )
    }
    plugin._client_factory = lambda c, h: _StubClient(routes)  # type: ignore
    os.environ["VT_API_KEY"] = "dummy"

    from mcpgateway.plugins.framework import ToolPostInvokePayload

    payload = ToolPostInvokePayload(name="writer", result=f"See {url} for details")
    ctx = PluginContext(global_context=GlobalContext(request_id="r4"))
    res = await plugin.tool_post_invoke(payload, ctx)
    assert res.violation is not None
    assert res.violation.code == "VT_URL_BLOCK"
