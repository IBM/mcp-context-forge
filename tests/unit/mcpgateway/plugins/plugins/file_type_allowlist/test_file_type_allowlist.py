# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/file_type_allowlist/test_file_type_allowlist.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for FileTypeAllowlistPlugin.
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePreFetchPayload,
    ResourcePostFetchPayload,
)
from mcpgateway.common.models import ResourceContent
from plugins.file_type_allowlist.file_type_allowlist import FileTypeAllowlistPlugin


@pytest.mark.asyncio
async def test_blocks_disallowed_extension_and_mime():
    plugin = FileTypeAllowlistPlugin(
        PluginConfig(
            name="fta",
            kind="plugins.file_type_allowlist.file_type_allowlist.FileTypeAllowlistPlugin",
            hooks=[ResourceHookType.RESOURCE_PRE_FETCH, ResourceHookType.RESOURCE_POST_FETCH],
            config={"allowed_extensions": [".md"], "allowed_mime_types": ["text/markdown"]},
        )
    )
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    # Extension blocked
    pre = await plugin.resource_pre_fetch(ResourcePreFetchPayload(uri="https://ex.com/data.pdf"), ctx)
    assert pre.violation is not None
    # MIME blocked
    content = ResourceContent(type="resource", id="345",uri="https://ex.com/file.md", mime_type="text/html", text="<p>x</p>")
    post = await plugin.resource_post_fetch(ResourcePostFetchPayload(uri=content.uri, content=content), ctx)
    assert post.violation is not None
