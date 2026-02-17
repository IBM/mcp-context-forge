# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URLReputationPlugin.
"""

import pytest
from unittest.mock import patch

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePreFetchPayload,
)

# Keep python and Rust with same test
@pytest.mark.asyncio
@pytest.mark.parametrize("use_python_fallback", [True, False])
async def test_blocks_blocklisted_domain_paths(use_python_fallback):

    if use_python_fallback:
        # Patch _RUST_AVAILABLE to False to force Python fallback
        patcher = patch("plugins.url_reputation.url_reputation._RUST_AVAILABLE", False)
        patcher.start()

    from plugins.url_reputation.url_reputation import URLReputationPlugin

    plugin = URLReputationPlugin(
        PluginConfig(
            name="urlrep",
            kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
            hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
            config={"blocked_domains": ["bad.example"]},
        )
    )

    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.resource_pre_fetch(
        ResourcePreFetchPayload(uri="https://api.bad.example/v1"), ctx
    )

    # Stop patching if it was applied
    if use_python_fallback:
        patcher.stop()

    # Assertions
    assert res.violation is not None
    assert res.violation.reason in ("Blocked domain", "Domain in blocked set")
