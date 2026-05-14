import asyncio

from cpex.framework import GlobalContext, PluginConfig, PluginContext, ToolHookType, ToolPreInvokePayload
from cpex.framework.memory import CopyOnWriteDict
import pytest

from plugins.sql_sanitizer.sql_sanitizer import SQLSanitizerPlugin


@pytest.mark.asyncio
async def test_nested():
    plugin = SQLSanitizerPlugin(
        PluginConfig(
            name="SQLSanitizer",
            description="Detects risky SQL and optionally strips comments or blocks",
            author="ContextForge",
            kind="plugins.sql_sanitizer.sql_sanitizer.SQLSanitizerPlugin",
            version="1.0.0",
            hooks=["prompt_pre_fetch", ToolHookType.TOOL_PRE_INVOKE],
            tags=["security", "sql", "validation"],
            priority=45,
            config={
                "fields": None,
                "blocked_statements": [
                    r"\bDROP\b",
                    r"\bTRUNCATE\b",
                    r"\bALTER\b",
                    r"\bGRANT\b",
                    r"\bREVOKE\b",
                ],
                "block_delete_without_where": True,
                "block_update_without_where": True,
                "strip_comments": True,
                "require_parameterization": False,
                "block_on_violation": True,
            },
        )
    )
    payload = CopyOnWriteDict(
        {
            "path": "sql.txt",
            "edits": [{"new": "DROP table tab1;", "old": "DROP table tab1;"}],
            "dry_run": False,
        }
    )
    result = await plugin.tool_pre_invoke(
        ToolPreInvokePayload(name="edit_file", args=payload),
        PluginContext(global_context=GlobalContext(request_id="1")),
    )
    assert result.violation

    payload = CopyOnWriteDict({"message": "DROP table asdf"})

    result = await plugin.tool_pre_invoke(
        ToolPreInvokePayload(name="echo", args=payload),
        PluginContext(global_context=GlobalContext(request_id="1")),
    )
    assert result.violation
