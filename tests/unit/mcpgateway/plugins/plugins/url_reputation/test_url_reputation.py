# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for URLReputationPlugin.
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePreFetchPayload,
)
from plugins.url_reputation.url_reputation import URLReputationPlugin


@pytest.mark.asyncio
async def test_blocks_blocklisted_domain():
    plugin = URLReputationPlugin(
        PluginConfig(
            name="urlrep",
            kind="plugins.url_reputation.url_reputation.URLReputationPlugin",
            hooks=[ResourceHookType.RESOURCE_PRE_FETCH],
            config={"blocked_domains": ["bad.example"]},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://api.bad.example/v1"), ctx)
    assert res.violation is not None
