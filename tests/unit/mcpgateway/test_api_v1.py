# -*- coding: utf-8 -*-
"""tests/unit/mcpgateway/test_api_v1.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for mcpgateway.api.v1.build_v1_router.

Each test exercises one or more branches of the router-assembly function:
  - Group A  : always-on inline routers passed as kwargs
  - Group B  : tool_plugin_bindings (ImportError-tolerant)
  - Group C  : feature-flagged optional routers
  - Group D  : auth cluster (email_auth_enabled)
  - Group E  : LLM cluster (llmchat_enabled)
  - Group F  : admin cluster (mcpgateway_admin_api_enabled)
"""

# Standard
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
from fastapi import APIRouter
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**flags) -> SimpleNamespace:
    """Build a minimal settings-like object for build_v1_router tests."""
    defaults = dict(
        mcpgateway_a2a_enabled=False,
        observability_enabled=False,
        mcpgateway_reverse_proxy_enabled=False,
        toolops_enabled=False,
        mcpgateway_tool_cancellation_enabled=False,
        metrics_cleanup_enabled=False,
        metrics_rollup_enabled=False,
        email_auth_enabled=False,
        sso_enabled=False,
        llmchat_enabled=False,
        mcpgateway_admin_api_enabled=False,
    )
    defaults.update(flags)
    return SimpleNamespace(**defaults)


def _sentinel_router(sentinel_path: str) -> APIRouter:
    """Return an APIRouter that contains one unique sentinel route."""
    r = APIRouter()
    r.add_api_route(sentinel_path, lambda: sentinel_path)
    return r


def _required_kwargs(**extras) -> dict:
    """Build the minimum kwargs needed by build_v1_router."""
    base = dict(
        protocol_router=_sentinel_router("/sentinel-protocol"),
        tool_router=_sentinel_router("/sentinel-tool"),
        resource_router=_sentinel_router("/sentinel-resource"),
        prompt_router=_sentinel_router("/sentinel-prompt"),
        gateway_router=_sentinel_router("/sentinel-gateway"),
        root_router=_sentinel_router("/sentinel-root"),
        server_router=_sentinel_router("/sentinel-server"),
        metrics_router=_sentinel_router("/sentinel-metrics"),
        tag_router=_sentinel_router("/sentinel-tag"),
        export_import_router=_sentinel_router("/sentinel-export"),
        a2a_router=_sentinel_router("/sentinel-a2a"),
    )
    base.update(extras)
    return base


def _route_paths(router: APIRouter) -> list[str]:
    """Collect all route paths registered on a router."""
    return [r.path for r in router.routes]


def _make_mock_router_module(sentinel_path: str) -> ModuleType:
    """Create a fake module containing a ``router`` attribute with one route."""
    mod = ModuleType("_mock")
    mod.router = _sentinel_router(sentinel_path)
    return mod


def _make_mock_router_module_named(attr_name: str, sentinel_path: str) -> ModuleType:
    """Like _make_mock_router_module but attribute name is configurable."""
    mod = ModuleType("_mock")
    setattr(mod, attr_name, _sentinel_router(sentinel_path))
    return mod


# ---------------------------------------------------------------------------
# Import target
# ---------------------------------------------------------------------------
from mcpgateway.api.v1 import build_v1_router  # noqa: E402


# ---------------------------------------------------------------------------
# Group A — always-on routers
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupA:
    """All required Group A routers are always included with /v1 prefix."""

    def test_router_prefix_is_v1(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert v1.prefix == "/v1"

    def test_protocol_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-protocol" in _route_paths(v1)

    def test_tool_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-tool" in _route_paths(v1)

    def test_resource_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-resource" in _route_paths(v1)

    def test_prompt_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-prompt" in _route_paths(v1)

    def test_gateway_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-gateway" in _route_paths(v1)

    def test_server_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-server" in _route_paths(v1)

    def test_metrics_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-metrics" in _route_paths(v1)

    def test_tag_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-tag" in _route_paths(v1)

    def test_export_import_router_included(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert "/v1/sentinel-export" in _route_paths(v1)

    def test_returns_apirouter_instance(self):
        settings = _settings()
        kwargs = _required_kwargs()
        v1 = build_v1_router(settings, **kwargs)
        assert isinstance(v1, APIRouter)


# ---------------------------------------------------------------------------
# Group B — tool_plugin_bindings (ImportError-tolerant)
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupB:
    """tool_plugin_bindings router is included when importable, skipped gracefully on ImportError."""

    def test_tool_plugin_bindings_included_when_importable(self):
        settings = _settings()
        mock_mod = _make_mock_router_module("/sentinel-tool-plugin")
        mock_mod.router = _sentinel_router("/sentinel-tool-plugin")

        with patch.dict(sys.modules, {"mcpgateway.routers.tool_plugin_bindings": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())

        assert "/v1/sentinel-tool-plugin" in _route_paths(v1)

    def test_tool_plugin_bindings_import_error_gracefully_skipped(self):
        """ImportError for tool_plugin_bindings must not raise; Group A routes still assembled."""
        settings = _settings()
        # Force ImportError by removing module from sys.modules and making import fail
        with patch.dict(sys.modules, {"mcpgateway.routers.tool_plugin_bindings": None}):
            v1 = build_v1_router(settings, **_required_kwargs())

        # Group A routes still present
        assert "/v1/sentinel-protocol" in _route_paths(v1)


# ---------------------------------------------------------------------------
# Group C — feature-flagged conditional routers
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupC:
    """Feature flags gate optional routers."""

    # A2A -----------------------------------------------------------------------

    def test_a2a_router_included_when_enabled(self):
        settings = _settings(mcpgateway_a2a_enabled=True)
        v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-a2a" in _route_paths(v1)

    def test_a2a_router_excluded_when_disabled(self):
        settings = _settings(mcpgateway_a2a_enabled=False)
        v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-a2a" not in _route_paths(v1)

    # Observability --------------------------------------------------------------

    def test_observability_router_included_when_enabled(self):
        settings = _settings(observability_enabled=True)
        mock_mod = _make_mock_router_module("/sentinel-observability")
        with patch.dict(sys.modules, {"mcpgateway.routers.observability": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-observability" in _route_paths(v1)

    def test_observability_router_excluded_when_disabled(self):
        settings = _settings(observability_enabled=False)
        mock_mod = _make_mock_router_module("/sentinel-observability")
        with patch.dict(sys.modules, {"mcpgateway.routers.observability": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-observability" not in _route_paths(v1)

    # Reverse proxy --------------------------------------------------------------

    def test_reverse_proxy_router_included_when_enabled(self):
        settings = _settings(mcpgateway_reverse_proxy_enabled=True)
        mock_mod = _make_mock_router_module("/sentinel-reverse-proxy")
        with patch.dict(sys.modules, {"mcpgateway.routers.reverse_proxy": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-reverse-proxy" in _route_paths(v1)

    def test_reverse_proxy_router_excluded_when_disabled(self):
        settings = _settings(mcpgateway_reverse_proxy_enabled=False)
        mock_mod = _make_mock_router_module("/sentinel-reverse-proxy")
        with patch.dict(sys.modules, {"mcpgateway.routers.reverse_proxy": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-reverse-proxy" not in _route_paths(v1)

    def test_reverse_proxy_import_error_gracefully_skipped(self):
        settings = _settings(mcpgateway_reverse_proxy_enabled=True)
        with patch.dict(sys.modules, {"mcpgateway.routers.reverse_proxy": None}):
            v1 = build_v1_router(settings, **_required_kwargs())
        # No exception; Group A intact
        assert "/v1/sentinel-protocol" in _route_paths(v1)

    # Toolops --------------------------------------------------------------------

    def test_toolops_router_included_when_enabled(self):
        settings = _settings(toolops_enabled=True)
        mock_mod = ModuleType("_mock")
        mock_mod.toolops_router = _sentinel_router("/sentinel-toolops")
        with patch.dict(sys.modules, {"mcpgateway.routers.toolops_router": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-toolops" in _route_paths(v1)

    def test_toolops_router_excluded_when_disabled(self):
        settings = _settings(toolops_enabled=False)
        mock_mod = ModuleType("_mock")
        mock_mod.toolops_router = _sentinel_router("/sentinel-toolops")
        with patch.dict(sys.modules, {"mcpgateway.routers.toolops_router": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-toolops" not in _route_paths(v1)

    def test_toolops_router_import_error_gracefully_skipped(self):
        """ImportError for toolops_router when enabled must not raise; Group A routes still assembled."""
        settings = _settings(toolops_enabled=True)
        with patch.dict(sys.modules, {"mcpgateway.routers.toolops_router": None}):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Group A routes still present
        assert "/v1/sentinel-protocol" in _route_paths(v1)

    # Cancellation ---------------------------------------------------------------

    def test_cancellation_router_included_when_enabled(self):
        settings = _settings(mcpgateway_tool_cancellation_enabled=True)
        mock_mod = _make_mock_router_module("/sentinel-cancellation")
        with patch.dict(sys.modules, {"mcpgateway.routers.cancellation_router": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-cancellation" in _route_paths(v1)

    def test_cancellation_router_excluded_when_disabled(self):
        settings = _settings(mcpgateway_tool_cancellation_enabled=False)
        mock_mod = _make_mock_router_module("/sentinel-cancellation")
        with patch.dict(sys.modules, {"mcpgateway.routers.cancellation_router": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-cancellation" not in _route_paths(v1)

    def test_cancellation_router_import_error_gracefully_skipped(self):
        """ImportError for cancellation_router when enabled must not raise; Group A routes still assembled."""
        settings = _settings(mcpgateway_tool_cancellation_enabled=True)
        with patch.dict(sys.modules, {"mcpgateway.routers.cancellation_router": None}):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Group A routes still present
        assert "/v1/sentinel-protocol" in _route_paths(v1)

    # Metrics maintenance --------------------------------------------------------

    def test_metrics_maintenance_included_when_cleanup_enabled(self):
        settings = _settings(metrics_cleanup_enabled=True)
        mock_mod = _make_mock_router_module("/sentinel-metrics-maint")
        with patch.dict(sys.modules, {"mcpgateway.routers.metrics_maintenance": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-metrics-maint" in _route_paths(v1)

    def test_metrics_maintenance_included_when_rollup_enabled(self):
        settings = _settings(metrics_rollup_enabled=True)
        mock_mod = _make_mock_router_module("/sentinel-metrics-maint")
        with patch.dict(sys.modules, {"mcpgateway.routers.metrics_maintenance": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-metrics-maint" in _route_paths(v1)

    def test_metrics_maintenance_excluded_when_both_disabled(self):
        settings = _settings(metrics_cleanup_enabled=False, metrics_rollup_enabled=False)
        mock_mod = _make_mock_router_module("/sentinel-metrics-maint")
        with patch.dict(sys.modules, {"mcpgateway.routers.metrics_maintenance": mock_mod}):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-metrics-maint" not in _route_paths(v1)


# ---------------------------------------------------------------------------
# Group D — auth cluster
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupD:
    """Auth/teams/tokens/RBAC cluster gated on email_auth_enabled."""

    def _auth_modules(self) -> dict:
        """Return sys.modules patches for the full auth cluster."""
        auth_mod = ModuleType("_mock_auth")
        auth_mod.auth_router = _sentinel_router("/sentinel-auth")

        email_auth_mod = ModuleType("_mock_email_auth")
        email_auth_mod.email_auth_router = _sentinel_router("/sentinel-email-auth")

        sso_mod = ModuleType("_mock_sso")
        sso_mod.sso_router = _sentinel_router("/sentinel-sso")

        teams_mod = ModuleType("_mock_teams")
        teams_mod.teams_router = _sentinel_router("/sentinel-teams")

        tokens_mod = ModuleType("_mock_tokens")
        tokens_mod.router = _sentinel_router("/sentinel-tokens")

        rbac_mod = ModuleType("_mock_rbac")
        rbac_mod.router = _sentinel_router("/sentinel-rbac")

        return {
            "mcpgateway.routers.auth": auth_mod,
            "mcpgateway.routers.email_auth": email_auth_mod,
            "mcpgateway.routers.sso": sso_mod,
            "mcpgateway.routers.teams": teams_mod,
            "mcpgateway.routers.tokens": tokens_mod,
            "mcpgateway.routers.rbac": rbac_mod,
        }

    def test_auth_cluster_excluded_when_email_auth_disabled(self):
        settings = _settings(email_auth_enabled=False)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        paths = _route_paths(v1)
        assert "/v1/sentinel-auth" not in paths
        assert "/v1/sentinel-teams/sentinel-teams" not in paths

    def test_auth_router_included_when_email_auth_enabled(self):
        settings = _settings(email_auth_enabled=True)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-auth" in _route_paths(v1)

    def test_teams_router_included_when_email_auth_enabled(self):
        settings = _settings(email_auth_enabled=True)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/teams/sentinel-teams" in _route_paths(v1)

    def test_tokens_router_included_when_email_auth_enabled(self):
        settings = _settings(email_auth_enabled=True)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-tokens" in _route_paths(v1)

    def test_rbac_router_included_when_email_auth_enabled(self):
        settings = _settings(email_auth_enabled=True)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-rbac" in _route_paths(v1)

    def test_sso_router_included_when_sso_enabled(self):
        settings = _settings(email_auth_enabled=True, sso_enabled=True)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-sso" in _route_paths(v1)

    def test_sso_router_excluded_when_sso_disabled(self):
        settings = _settings(email_auth_enabled=True, sso_enabled=False)
        with patch.dict(sys.modules, self._auth_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-sso" not in _route_paths(v1)

    def test_sso_router_import_error_gracefully_skipped(self):
        """ImportError for sso_router when sso_enabled=True must not raise; other auth routers still assembled."""
        settings = _settings(email_auth_enabled=True, sso_enabled=True)
        mods = self._auth_modules()
        mods["mcpgateway.routers.sso"] = None  # Force ImportError for SSO only
        with patch.dict(sys.modules, mods):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Auth router still included even when SSO import fails
        assert "/v1/sentinel-auth" in _route_paths(v1)
        # SSO route not present
        assert "/v1/sentinel-sso" not in _route_paths(v1)

    def test_auth_import_error_gracefully_skipped(self):
        """ImportError for auth routers must not prevent Group A from assembling."""
        settings = _settings(email_auth_enabled=True)
        with patch.dict(sys.modules, {
            "mcpgateway.routers.auth": None,
            "mcpgateway.routers.email_auth": None,
            "mcpgateway.routers.teams": None,
            "mcpgateway.routers.tokens": None,
            "mcpgateway.routers.rbac": None,
        }):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Group A intact even when auth cluster fails
        assert "/v1/sentinel-protocol" in _route_paths(v1)


# ---------------------------------------------------------------------------
# Group E — LLM cluster
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupE:
    """LLM chat and config routers gated on llmchat_enabled."""

    def _llm_modules(self) -> dict:
        llmchat_mod = ModuleType("_mock_llmchat")
        llmchat_mod.llmchat_router = _sentinel_router("/sentinel-llmchat")

        llm_config_mod = ModuleType("_mock_llm_config")
        llm_config_mod.llm_config_router = _sentinel_router("/sentinel-llm-config")

        llm_admin_mod = ModuleType("_mock_llm_admin")
        llm_admin_mod.llm_admin_router = _sentinel_router("/sentinel-llm-admin")

        return {
            "mcpgateway.routers.llmchat_router": llmchat_mod,
            "mcpgateway.routers.llm_config_router": llm_config_mod,
            "mcpgateway.routers.llm_admin_router": llm_admin_mod,
        }

    def test_llmchat_router_included_when_enabled(self):
        settings = _settings(llmchat_enabled=True)
        with patch.dict(sys.modules, self._llm_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-llmchat" in _route_paths(v1)

    def test_llmchat_router_excluded_when_disabled(self):
        settings = _settings(llmchat_enabled=False)
        with patch.dict(sys.modules, self._llm_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-llmchat" not in _route_paths(v1)

    def test_llm_config_router_included_when_llmchat_enabled(self):
        settings = _settings(llmchat_enabled=True)
        with patch.dict(sys.modules, self._llm_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/llm/sentinel-llm-config" in _route_paths(v1)

    def test_llm_admin_router_included_when_llmchat_enabled(self):
        settings = _settings(llmchat_enabled=True)
        with patch.dict(sys.modules, self._llm_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/admin/llm/sentinel-llm-admin" in _route_paths(v1)

    def test_llm_import_error_gracefully_skipped(self):
        settings = _settings(llmchat_enabled=True)
        with patch.dict(sys.modules, {
            "mcpgateway.routers.llmchat_router": None,
            "mcpgateway.routers.llm_config_router": None,
            "mcpgateway.routers.llm_admin_router": None,
        }):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Group A intact
        assert "/v1/sentinel-protocol" in _route_paths(v1)


# ---------------------------------------------------------------------------
# Group F — admin cluster
# ---------------------------------------------------------------------------

class TestBuildV1RouterGroupF:
    """Admin router gated on mcpgateway_admin_api_enabled."""

    def _admin_modules(self) -> dict:
        admin_mod = ModuleType("_mock_admin")
        admin_mod.admin_router = _sentinel_router("/sentinel-admin")
        admin_mod.set_logging_service = MagicMock()
        admin_mod.validate_section_permissions = MagicMock()

        runtime_admin_mod = ModuleType("_mock_runtime_admin")
        runtime_admin_mod.runtime_admin_router = _sentinel_router("/sentinel-runtime-admin")

        well_known_mod = ModuleType("_mock_well_known")
        well_known_mod.admin_router = _sentinel_router("/sentinel-well-known")

        return {
            "mcpgateway.admin": admin_mod,
            "mcpgateway.routers.runtime_admin_router": runtime_admin_mod,
            "mcpgateway.routers.well_known": well_known_mod,
        }

    def test_admin_router_included_when_admin_api_enabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        with patch.dict(sys.modules, self._admin_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-admin" in _route_paths(v1)

    def test_runtime_admin_router_included_when_admin_api_enabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        with patch.dict(sys.modules, self._admin_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/admin/runtime/sentinel-runtime-admin" in _route_paths(v1)

    def test_well_known_included_in_v1_when_admin_api_enabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        with patch.dict(sys.modules, self._admin_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        assert "/v1/sentinel-well-known" in _route_paths(v1)

    def test_admin_router_excluded_when_admin_api_disabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=False)
        with patch.dict(sys.modules, self._admin_modules()):
            v1 = build_v1_router(settings, **_required_kwargs())
        paths = _route_paths(v1)
        assert "/v1/sentinel-admin" not in paths

    def test_admin_import_error_gracefully_skipped(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        with patch.dict(sys.modules, {
            "mcpgateway.admin": None,
            "mcpgateway.routers.runtime_admin_router": None,
            "mcpgateway.routers.well_known": None,
        }):
            v1 = build_v1_router(settings, **_required_kwargs())
        # Group A intact even when admin cluster fails
        assert "/v1/sentinel-protocol" in _route_paths(v1)

    def test_set_logging_service_called_when_admin_enabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        mods = self._admin_modules()
        with patch.dict(sys.modules, mods):
            build_v1_router(settings, **_required_kwargs())
        mods["mcpgateway.admin"].set_logging_service.assert_called_once()

    def test_validate_section_permissions_called_when_admin_enabled(self):
        settings = _settings(mcpgateway_admin_api_enabled=True)
        mods = self._admin_modules()
        with patch.dict(sys.modules, mods):
            build_v1_router(settings, **_required_kwargs())
        mods["mcpgateway.admin"].validate_section_permissions.assert_called_once()
