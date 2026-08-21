# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service_preview.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for ToolService.preview_tool_invocation (#5629).

preview_tool_invocation shares tool resolution/RBAC with invoke_tool via
_resolve_tool_for_invocation, so _resolve_tool_for_invocation is mocked directly
here rather than re-exercising the full DB/cache lookup already covered by
test_tool_service.py — these tests are about the preview-specific behavior
(input validation, federation policy, preview_safe hook filtering, response
shape) built on top of that shared resolution.
"""

# Standard
from contextlib import suppress
from unittest.mock import AsyncMock, Mock, patch

# Third-Party
from cpex.framework import PluginError, PluginMode, PluginViolationError
import pytest

# First-Party
from mcpgateway.services.tool_service import ResolvedTool, ToolNotFoundError, ToolService


def _resolved(tool_payload, gateway_payload=None):
    """Build a ResolvedTool with only the fields preview_tool_invocation reads."""
    return ResolvedTool(is_direct_proxy=False, tool=None, gateway=None, tool_payload=tool_payload, gateway_payload=gateway_payload)


def _local_tool_payload(**overrides):
    payload = {
        "id": "1",
        "name": "test_tool",
        "gateway_id": None,
        "team_id": "team-a",
        "input_schema": {"type": "object", "properties": {"param": {"type": "string"}}, "required": ["param"]},
        "annotations": {"readOnlyHint": True},
    }
    payload.update(overrides)
    return payload


def _federated_tool_payload(**overrides):
    payload = _local_tool_payload(gateway_id="gw-1")
    payload.update(overrides)
    return payload


@pytest.fixture
def service():
    """A bare ToolService instance (no plugin manager unless a test opts in)."""
    svc = ToolService()
    svc.get_plugin_manager = AsyncMock(return_value=None)
    return svc


class TestPreviewToolInvocationHappyPath:
    """Local vs. federated targeting, and the shared-resolution error path."""

    @pytest.mark.asyncio
    async def test_does_not_commit_or_close_caller_session(self, service):
        """Preview makes no HTTP call after resolution, so it must not commit/close the
        caller's session -- that session belongs to the route's get_db() dependency."""
        db = Mock()
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=None)
        ):
            await service.preview_tool_invocation(db, "test_tool", {"param": "value"})

        db.commit.assert_not_called()
        db.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_tool_happy_path(self, service, test_db):
        """Local tool (gateway_id is None): validated, target.kind == 'local', no gateway_name."""
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=None)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.validated is True
        assert result.resolved_arguments == {"param": "value"}
        assert result.target.kind == "local"
        assert result.target.gateway_name is None
        assert result.annotations.read_only_hint is True
        assert result.pre_hooks_run == []
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_federated_tool_no_leak(self, service, test_db):
        """Federated tool: target.kind == 'federated', gateway_name set, no wire call, no
        gateway URL/auth/transport leaked anywhere in the serialized response (#5629)."""
        gateway_payload = {
            "name": "remote-gw",
            "url": "https://internal.example.com/mcp",
            "auth_type": "bearer",
            "auth_value": "SUPER_SECRET_TOKEN_MARKER",
            "transport": "STREAMABLEHTTP",
            "client_key": "PRIVATE_KEY_MARKER",
        }
        with patch.object(
            service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_federated_tool_payload(), gateway_payload))
        ), patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.target.kind == "federated"
        assert result.target.gateway_name == "remote-gw"

        body = result.model_dump_json()
        for secret in ("internal.example.com", "SUPER_SECRET_TOKEN_MARKER", "STREAMABLEHTTP", "PRIVATE_KEY_MARKER", "bearer"):
            assert secret not in body, f"preview response leaked gateway-internal value: {secret!r}"

    @pytest.mark.asyncio
    async def test_no_dispatch_no_http_call(self, service, test_db):
        """Preview never touches the HTTP client, even for a federated tool."""
        service._http_client = AsyncMock()
        with patch.object(
            service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_federated_tool_payload(), {"name": "remote-gw"}))
        ), patch.object(service, "_get_plugin_manager", AsyncMock(return_value=None)):
            await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        service._http_client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_not_found_propagates(self, service, test_db):
        """Resolution failures (not-found / no-access / wrong-team) surface identically
        to invoke_tool's, since both share _resolve_tool_for_invocation."""
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(side_effect=ToolNotFoundError("Tool not found: nope"))):
            with pytest.raises(ToolNotFoundError):
                await service.preview_tool_invocation(test_db, "nope", {})


class TestPreviewToolInvocationSchemaValidation:
    """Input-schema validation against the tool's declared input_schema."""

    @pytest.mark.asyncio
    async def test_valid_arguments(self, service, test_db):
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.validated is True
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_invalid_arguments_reported_not_raised(self, service, test_db):
        """Schema-invalid arguments produce validated=False + a warning, not an exception --
        a preview should report what live invocation would reject, not 500."""
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))):
            # required "param" missing
            result = await service.preview_tool_invocation(test_db, "test_tool", {})

        assert result.validated is False
        assert any(w.code == "invalid_arguments" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_no_input_schema_defaults_to_validated(self, service, test_db):
        """Tools with no declared input_schema are trivially considered validated."""
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload(input_schema=None)))):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"anything": "goes"})

        assert result.validated is True


class TestPreviewToolInvocationPluginHooks:
    """preview_safe-tagged TOOL_PRE_INVOKE hooks run; everything else is a warning."""

    def _plugin_manager_with_refs(self, refs, invoke_side_effect=None):
        pm = Mock()
        pm.has_hooks_for = Mock(return_value=True)
        pm._registry = Mock()
        pm._registry.get_hook_refs_for_hook = Mock(return_value=refs)
        pm.invoke_hook_for_plugin = AsyncMock(side_effect=invoke_side_effect)
        return pm

    @staticmethod
    def _hook_ref(name, tags, mode=PluginMode.SEQUENTIAL):
        ref = Mock()
        ref.plugin_ref = Mock()
        ref.plugin_ref.name = name
        ref.plugin_ref.tags = tags
        ref.plugin_ref.mode = mode
        return ref

    @pytest.mark.asyncio
    async def test_no_plugin_manager_no_hooks(self, service, test_db):
        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=None)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == []
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_preview_safe_hook_runs_and_is_reported(self, service, test_db):
        ref = self._hook_ref("safe_plugin", ["preview_safe"])
        pm = self._plugin_manager_with_refs([ref])

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == ["safe_plugin"]
        assert result.warnings == []
        pm.invoke_hook_for_plugin.assert_awaited_once()
        assert pm.invoke_hook_for_plugin.call_args.kwargs["name"] == "safe_plugin"

    @pytest.mark.asyncio
    async def test_untagged_hook_is_skipped_and_warned(self, service, test_db):
        """No plugin ships with the preview_safe tag today (#5629) -- this is the
        expected default behavior until a plugin author opts in, not a bug."""
        ref = self._hook_ref("untagged_plugin", [])
        pm = self._plugin_manager_with_refs([ref])

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == []
        pm.invoke_hook_for_plugin.assert_not_awaited()
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "hook_not_previewed"
        assert result.warnings[0].hook == "untagged_plugin"

    @pytest.mark.asyncio
    async def test_hook_violation_folds_into_warning_not_raised(self, service, test_db):
        """A preview_safe hook that would deny in production must not blow up preview --
        it should be reported as a warning so the caller can still see the rest of the
        envelope (annotations, target, etc.)."""
        ref = self._hook_ref("strict_plugin", ["preview_safe"])
        pm = self._plugin_manager_with_refs([ref], invoke_side_effect=PluginViolationError("blocked by policy"))

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == []
        assert any(w.code == "preview_hook_violation" and w.hook == "strict_plugin" for w in result.warnings)
        # The rest of the envelope must still be populated -- a hook violation isn't fatal to preview.
        assert result.target.kind == "local"

    @pytest.mark.asyncio
    async def test_hook_error_folds_into_warning_not_raised(self, service, test_db):
        """A crashing/unavailable plugin must not take down preview either."""
        ref = self._hook_ref("flaky_plugin", ["preview_safe"])
        pm = self._plugin_manager_with_refs([ref], invoke_side_effect=PluginError(error=Mock(message="plugin crashed")))

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert any(w.code == "preview_hook_error" and w.hook == "flaky_plugin" for w in result.warnings)

    @pytest.mark.asyncio
    async def test_registry_reach_through_failure_degrades_gracefully(self, service, test_db):
        """If cpex's internal registry shape ever changes, preview must degrade to
        'no hooks previewed' rather than 500 (#5629 known-coupling note)."""
        pm = Mock()
        pm.has_hooks_for = Mock(return_value=True)
        pm._registry = Mock()
        pm._registry.get_hook_refs_for_hook = Mock(side_effect=AttributeError("shape changed"))

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == []
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_disabled_plugin_is_filtered_even_if_preview_safe_tagged(self, service, test_db):
        """cpex still registers a stub HookRef for mode: disabled plugins; only its own
        aggregate executor filters them out before dispatch. Since preview calls
        invoke_hook_for_plugin directly (bypassing that executor), it must apply the same
        DISABLED filter itself -- otherwise a disabled plugin would be reported as run."""
        ref = self._hook_ref("disabled_plugin", ["preview_safe"], mode=PluginMode.DISABLED)
        pm = self._plugin_manager_with_refs([ref])

        with patch.object(service, "_resolve_tool_for_invocation", AsyncMock(return_value=_resolved(_local_tool_payload()))), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=pm)
        ):
            result = await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})

        assert result.pre_hooks_run == []
        assert result.warnings == [], "a disabled plugin should be silently excluded, not reported as skipped/not-previewed either"
        pm.invoke_hook_for_plugin.assert_not_awaited()


class TestSharedResolutionPath:
    """#5629 explicit requirement: preview and live invocation must call the same
    internal resolution function, or previews can silently lie."""

    @pytest.mark.asyncio
    async def test_invoke_tool_and_preview_call_same_resolver(self, service, test_db):
        resolved = _resolved(_local_tool_payload())
        mock_resolve = AsyncMock(return_value=resolved)

        with patch.object(service, "_resolve_tool_for_invocation", mock_resolve), patch.object(
            service, "_get_plugin_manager", AsyncMock(return_value=None)
        ):
            await service.preview_tool_invocation(test_db, "test_tool", {"param": "value"})
            # invoke_tool will fail past resolution against this minimal synthetic payload
            # (no real HTTP/MCP target configured) -- only the shared resolution call matters here.
            with suppress(Exception):
                await service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert mock_resolve.await_count == 2, "invoke_tool and preview_tool_invocation must both call _resolve_tool_for_invocation"
