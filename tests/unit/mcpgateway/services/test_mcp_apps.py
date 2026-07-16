# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_apps.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the minimal MCP Apps helpers.
"""

# Standard
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import ServerCapabilities
from mcpgateway.services import mcp_apps as mcp_apps_mod
from mcpgateway.services.mcp_apps import (
    apply_resource_meta,
    apply_tool_meta,
    build_mcp_apps_capabilities,
    filter_model_visible_tools,
    is_app_visible_tool,
    MCPAppSessionCleanupService,
    mcp_app_session_service,
    MCP_UI_EXTENSION,
    MCPAppsValidationError,
    merge_mcp_protocol_meta,
    serialize_resource_content_for_mcp,
    validate_extension_metadata,
    validate_ui_resource,
)


def test_server_capabilities_accept_extensions() -> None:
    """ServerCapabilities should serialize extension capabilities."""
    caps = ServerCapabilities(extensions={MCP_UI_EXTENSION: {"version": "test"}})

    assert caps.model_dump(exclude_none=True)["extensions"][MCP_UI_EXTENSION]["version"] == "test"


def test_build_mcp_apps_capabilities_respects_flag_and_authorization(monkeypatch) -> None:
    """MCP Apps capability is advertised only when enabled and authorized."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

    assert MCP_UI_EXTENSION in build_mcp_apps_capabilities(authorized=True)
    assert build_mcp_apps_capabilities(authorized=False) == {}

    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
    assert build_mcp_apps_capabilities(authorized=True) == {}


def test_validate_extension_metadata_rejects_unsafe_csp() -> None:
    """MCP Apps metadata rejects unsafe CSP sources."""
    with pytest.raises(MCPAppsValidationError, match="'unsafe-inline' is not allowed"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"resourceDomains": ["'unsafe-inline'"]}}})

    with pytest.raises(MCPAppsValidationError, match="'unsafe-inline' is not allowed"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"connectDomains": ["'unsafe-inline'"]}}})

    with pytest.raises(MCPAppsValidationError, match="Wildcard CSP sources"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"resourceDomains": ["*"]}}})

    with pytest.raises(MCPAppsValidationError, match="Wildcard CSP sources"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"connectDomains": ["https://*.evil.example"]}}})

    with pytest.raises(MCPAppsValidationError, match="Blocked MCP Apps CSP source"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"resourceDomains": ["data:image/png;base64,abc"]}}})


def test_validate_extension_metadata_applies_content_security_to_csp_sources(monkeypatch) -> None:
    """MCP Apps CSP source validation should honor centralized content-security rules."""
    # First-Party
    from mcpgateway.services.content_security import ContentPatternError

    class FakeContentSecurityService:
        def __init__(self) -> None:
            self.checked_sources = []

        def detect_malicious_patterns(self, content, content_type="content", user_email=None, ip_address=None) -> None:
            self.checked_sources.append((content, content_type))
            if content == "https://blocked.example":
                raise ContentPatternError("blocked.example", content_type=content_type, violation_type="custom_blocked_pattern")

    fake_service = FakeContentSecurityService()
    monkeypatch.setattr(mcp_apps_mod, "get_content_security_service", lambda: fake_service)

    with pytest.raises(MCPAppsValidationError, match="MCP Apps CSP source"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"connectDomains": ["https://blocked.example"]}}})

    assert fake_service.checked_sources == [("https://blocked.example", "MCP Apps CSP source")]


def test_validate_ui_resource_requires_text_html_when_enabled(monkeypatch) -> None:
    """ui:// resources must be MCP App HTML when MCP Apps are enabled."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

    policy = {MCP_UI_EXTENSION: {"csp": {"resourceDomains": ["'self'"]}, "sandbox": ["allow-scripts"]}}
    validate_ui_resource("ui://example/widget", "text/html;profile=mcp-app", policy)
    validate_ui_resource("ui://example/widget", "text/html; charset=utf-8; profile=mcp-app", policy)
    with pytest.raises(MCPAppsValidationError):
        validate_ui_resource("ui://example/widget", "text/html", policy)
    with pytest.raises(MCPAppsValidationError):
        validate_ui_resource("ui://example/widget", "application/json", policy)


def test_model_visible_filter_hides_app_only_tools(monkeypatch) -> None:
    """App-only helper tools should not appear in model-facing tool lists."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    model_tool = SimpleNamespace(name="model_tool", extension_metadata={MCP_UI_EXTENSION: {"visibility": ["model"]}})
    app_tool = SimpleNamespace(name="app_tool", extension_metadata={MCP_UI_EXTENSION: {"visibility": ["app"]}})

    assert filter_model_visible_tools([model_tool, app_tool]) == [model_tool]
    assert is_app_visible_tool(app_tool) is True


def test_apply_resource_meta_projects_ui_policy(monkeypatch) -> None:
    """Known UI resource policy should project into MCP _meta."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    payload: dict = {}

    apply_resource_meta(payload, {MCP_UI_EXTENSION: {"csp": {"resourceDomains": ["'self'"]}, "sandbox": ["allow-scripts"], "permissions": ["clipboard-read"]}})

    assert payload["_meta"]["ui"]["sandbox"] == ["allow-scripts"]
    assert payload["_meta"]["ui"]["permissions"] == ["clipboard-read"]


def test_merge_mcp_protocol_meta_projects_ui_to_extension_metadata() -> None:
    """Upstream MCP _meta.ui should be stored as ContextForge MCP Apps metadata."""
    payload = {"_meta": {"ui": {"resourceUri": "ui://widgets/example", "visibility": ["model"]}}}

    merge_mcp_protocol_meta(payload)

    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["resourceUri"] == "ui://widgets/example"
    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["visibility"] == ["model"]


def test_merge_mcp_protocol_meta_ignores_missing_ui_and_merges_existing_metadata() -> None:
    """Protocol metadata merge should ignore non-UI metadata and preserve MCP Apps data."""
    payload = {"_meta": {"ui": {}}}
    merge_mcp_protocol_meta(payload)
    assert "extensionMetadata" not in payload

    payload = {
        "_meta": {"ui": {"resourceUri": "ui://widgets/example"}},
        "extensionMetadata": {MCP_UI_EXTENSION: {"visibility": ["model"]}},
    }
    merge_mcp_protocol_meta(payload)

    assert payload["extensionMetadata"][MCP_UI_EXTENSION] == {
        "visibility": ["model"],
        "resourceUri": "ui://widgets/example",
    }


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ("bad", "extensionMetadata must be an object"),
        ({MCP_UI_EXTENSION: {"resourceUri": "http://example.com"}}, "resourceUri must use the ui:// scheme"),
        ({MCP_UI_EXTENSION: {"visibility": ["operator"]}}, "visibility entries"),
        ({MCP_UI_EXTENSION: {"csp": "default-src 'self'"}}, "csp must be an object"),
        ({MCP_UI_EXTENSION: {"csp": {"script-src": ["'self'"]}}}, "Unsupported MCP Apps CSP directive"),
        ({MCP_UI_EXTENSION: {"sandbox": 123}}, "sandbox must be a string or list of strings"),
        ({MCP_UI_EXTENSION: {"permissions": ["clipboard_read"]}}, "Unsupported MCP Apps permission"),
    ],
)
def test_validate_extension_metadata_rejects_malformed_mcp_apps_values(metadata, message) -> None:
    """MCP Apps metadata should fail closed for malformed policy fields."""
    with pytest.raises(MCPAppsValidationError, match=message):
        validate_extension_metadata(metadata)


def test_validate_extension_metadata_rejects_malformed_permission_map() -> None:
    """Permission maps must use known permission names with object values."""
    with pytest.raises(MCPAppsValidationError, match="Unsupported MCP Apps permission"):
        validate_extension_metadata({MCP_UI_EXTENSION: {"permissions": {"clipboardWrite": True}}})


def test_validate_extension_metadata_accepts_absent_ui_block() -> None:
    """Unknown metadata can be stored when known MCP Apps policy is absent."""
    validate_extension_metadata({"io.example/custom": {"ok": True}})


def test_validate_extension_metadata_accepts_string_visibility_and_csp_source() -> None:
    """String-or-list metadata fields should normalize as valid string lists."""
    validate_extension_metadata(
        {
            MCP_UI_EXTENSION: {
                "resourceUri": "ui://widgets/example",
                "visibility": "app",
                "csp": {"resourceDomains": "'self'"},
                "sandbox": "allow-scripts",
                "permissions": "clipboard-read",
            }
        }
    )


def test_validate_extension_metadata_accepts_current_app_csp_and_permissions() -> None:
    """Current MCP Apps CSP and permissions metadata should be accepted."""
    validate_extension_metadata(
        {
            MCP_UI_EXTENSION: {
                "csp": {"connectDomains": ["https://api.example.com"], "resourceDomains": ["https://cdn.example.com"]},
                "permissions": {"clipboardWrite": {}},
            }
        }
    )


def test_apply_tool_meta_emits_default_model_visibility(monkeypatch) -> None:
    """Tools with UI resources should advertise ContextForge's model-only default."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    payload: dict = {}

    apply_tool_meta(payload, {MCP_UI_EXTENSION: {"resourceUri": "ui://widgets/example"}})

    assert payload["_meta"]["ui"]["resourceUri"] == "ui://widgets/example"
    assert payload["_meta"]["ui"]["visibility"] == ["model"]


def test_apply_resource_meta_noops_without_enabled_extension_or_ui(monkeypatch) -> None:
    """Resource metadata projection should no-op when disabled or UI metadata is absent."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
    payload: dict = {}
    apply_resource_meta(payload, {MCP_UI_EXTENSION: {"sandbox": ["allow-scripts"]}})
    assert payload == {}

    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    apply_resource_meta(payload, {"io.example/custom": {"sandbox": ["allow-scripts"]}})
    assert payload == {}


def test_serialize_resource_content_for_mcp_preserves_mime_and_meta() -> None:
    """Legacy resource content should serialize to MCP resources/read content."""
    # First-Party
    from mcpgateway.common.models import ResourceContent

    content = ResourceContent(type="resource", id="r1", uri="ui://widgets/example", mimeType="text/html;profile=mcp-app", text="<html></html>", _meta={"ui": {"prefersBorder": True}})

    assert serialize_resource_content_for_mcp(content) == {
        "uri": "ui://widgets/example",
        "mimeType": "text/html;profile=mcp-app",
        "text": "<html></html>",
        "_meta": {"ui": {"prefersBorder": True}},
    }


def test_serialize_resource_content_for_mcp_handles_blob_and_sdk_models() -> None:
    """Resource content serialization should handle legacy and SDK blob shapes."""
    # First-Party
    from mcpgateway.common.models import BlobResourceContents, ResourceContent

    legacy_blob = ResourceContent(type="resource", id="r1", uri="ui://widgets/blob", mimeType="application/octet-stream", blob=b"xy", _meta={"source": "legacy"})
    assert serialize_resource_content_for_mcp(legacy_blob) == {
        "uri": "ui://widgets/blob",
        "mimeType": "application/octet-stream",
        "blob": "eHk=",
        "_meta": {"source": "legacy"},
    }

    sdk_blob = BlobResourceContents(uri="ui://widgets/sdk", mimeType="application/octet-stream", blob="already-base64", _meta={"source": "sdk"})
    assert serialize_resource_content_for_mcp(sdk_blob) == {
        "uri": "ui://widgets/sdk",
        "mimeType": "application/octet-stream",
        "blob": "already-base64",
        "_meta": {"source": "sdk"},
    }


def test_serialize_resource_content_for_mcp_normalizes_mapping_and_generic_payloads() -> None:
    """Resource content serialization should normalize mapping and generic payload shapes."""
    mapping_payload = {"mime_type": "text/html", "meta": {"ui": True}, "text": "<html></html>"}
    assert serialize_resource_content_for_mcp(mapping_payload, fallback_uri="ui://widgets/mapping") == {
        "uri": "ui://widgets/mapping",
        "mimeType": "text/html",
        "text": "<html></html>",
        "_meta": {"ui": True},
    }

    attr_blob = SimpleNamespace(uri="ui://widgets/attr", mime_type="application/octet-stream", blob=b"xy", meta={"source": "attr"})
    assert serialize_resource_content_for_mcp(attr_blob) == {
        "uri": "ui://widgets/attr",
        "mimeType": "application/octet-stream",
        "blob": "eHk=",
        "_meta": {"source": "attr"},
    }

    attr_blob_string = SimpleNamespace(uri="ui://widgets/attr-string", blob="already-base64")
    assert serialize_resource_content_for_mcp(attr_blob_string) == {
        "uri": "ui://widgets/attr-string",
        "blob": "already-base64",
    }

    assert serialize_resource_content_for_mcp("plain text", fallback_uri="ui://widgets/text") == {
        "uri": "ui://widgets/text",
        "text": "plain text",
    }
    assert serialize_resource_content_for_mcp(b"xy", fallback_uri="ui://widgets/raw") == {
        "uri": "ui://widgets/raw",
        "blob": "eHk=",
    }


def test_serialize_resource_content_for_mcp_handles_model_dump_and_string_fallback() -> None:
    """Resource content serialization should fall back to model_dump or string payloads."""
    dumpable = MagicMock()
    dumpable.model_dump.return_value = {"text": "dumped"}

    assert serialize_resource_content_for_mcp(dumpable, fallback_uri="ui://widgets/dump") == {
        "text": "dumped",
        "uri": "ui://widgets/dump",
    }
    dumpable.model_dump.assert_called_once_with(by_alias=True, exclude_none=True)

    class StringOnly:
        def __str__(self) -> str:
            return "stringified"

    assert serialize_resource_content_for_mcp(StringOnly(), fallback_uri="ui://widgets/string") == {
        "uri": "ui://widgets/string",
        "text": "stringified",
    }


def test_create_app_session_persists_ttl_bound_record(monkeypatch) -> None:
    """AppBridge session creation should persist and return the database record."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_session_ttl", 60)
    db = MagicMock()
    db.refresh.side_effect = lambda session: setattr(session, "refreshed", True)

    session = mcp_app_session_service.create_session(
        db,
        mcp_session_id="mcp-session-1",
        user_email="user@example.com",
        server_id="server-1",
        resource_uri="ui://widgets/example",
        token_teams=["team-1"],
    )

    db.add.assert_called_once_with(session)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(session)
    assert session.refreshed is True
    assert session.mcp_session_id == "mcp-session-1"
    assert session.token_teams == ["team-1"]


def test_cleanup_expired_sessions_rolls_back_on_failure() -> None:
    """Cleanup failures should roll back the database session."""
    db = MagicMock()
    db.execute.side_effect = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        mcp_app_session_service.cleanup_expired_sessions(db)

    db.rollback.assert_called_once()


def test_cleanup_expired_sessions_commits_each_deleted_batch() -> None:
    """Cleanup should release each expired-session batch with its own commit."""
    first_ids = MagicMock()
    first_ids.scalars.return_value.all.return_value = ["session-1", "session-2"]
    first_delete = MagicMock(rowcount=2)
    second_ids = MagicMock()
    second_ids.scalars.return_value.all.return_value = ["session-3", "session-4"]
    second_delete = MagicMock(rowcount=2)
    third_ids = MagicMock()
    third_ids.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute.side_effect = [first_ids, first_delete, second_ids, second_delete, third_ids]

    deleted_count = mcp_app_session_service.cleanup_expired_sessions(db, batch_size=2)

    assert deleted_count == 4
    assert db.commit.call_count == 2


@pytest.mark.asyncio
async def test_cleanup_service_start_and_shutdown(monkeypatch) -> None:
    """Cleanup service should respect disabled state and cancel a running task on shutdown."""
    disabled_service = MCPAppSessionCleanupService(enabled=False)
    await disabled_service.start()
    assert disabled_service._cleanup_task is None

    running_service = MCPAppSessionCleanupService(enabled=True)

    async def never_finishes() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(running_service, "_cleanup_loop", never_finishes)
    await running_service.start()
    assert running_service._cleanup_task is not None
    await running_service.shutdown()
    assert running_service._cleanup_task.cancelled()


@pytest.mark.asyncio
async def test_cleanup_service_cleanup_once_uses_fresh_session(monkeypatch) -> None:
    """One cleanup pass should use a fresh database session and configured batch size."""
    db = MagicMock()
    session_service = MagicMock()
    session_service.cleanup_expired_sessions.return_value = 3

    @contextmanager
    def fake_fresh_db_session():
        yield db

    monkeypatch.setattr(mcp_apps_mod, "fresh_db_session", fake_fresh_db_session)
    service = MCPAppSessionCleanupService(session_service=session_service, batch_size=7)

    assert await service.cleanup_once() == 3
    session_service.cleanup_expired_sessions.assert_called_once_with(db, batch_size=7)


@pytest.mark.asyncio
async def test_cleanup_loop_runs_after_timeout_and_logs_deletions(monkeypatch) -> None:
    """Cleanup loop should run cleanup after its interval expires."""
    service = MCPAppSessionCleanupService(enabled=True, interval_seconds=1)

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        service._shutdown_event.set()
        raise asyncio.TimeoutError

    cleanup_once = AsyncMock(return_value=2)
    monkeypatch.setattr(mcp_apps_mod.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(service, "cleanup_once", cleanup_once)

    await service._cleanup_loop()

    cleanup_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_loop_logs_and_recovers_from_cleanup_errors(monkeypatch) -> None:
    """Cleanup loop should log cleanup failures and keep running until shutdown."""
    service = MCPAppSessionCleanupService(enabled=True, interval_seconds=1)

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    async def fake_sleep(delay):
        service._shutdown_event.set()

    cleanup_once = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    monkeypatch.setattr(mcp_apps_mod.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(mcp_apps_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(service, "cleanup_once", cleanup_once)

    await service._cleanup_loop()

    cleanup_once.assert_awaited_once()
