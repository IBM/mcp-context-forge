# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_legacy_router.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

tests/unit/mcpgateway/test_legacy_router.py
Unit tests for mcpgateway.api.v1.build_legacy_router.

Mirrors the structure of test_api_v1.py.  Each test exercises a branch of
the router-assembly function via the legacy (unversioned) mount path.

Groups:
  - Group A  : always-on inline routers — paths must NOT have /v1 prefix
  - Group B  : tool_plugin_bindings (ImportError-tolerant)
  - Group C  : feature-flagged optional routers
  - Group D  : auth cluster (email_auth_enabled)
  - Group E  : LLM cluster (llmchat_enabled)
  - Group F  : admin cluster (mcpgateway_admin_api_enabled)
  - Disabled : legacy_api_enabled=False is handled by the caller (main.py);
               this file tests build_legacy_router directly — a separate
               integration test for the flag lives in test_main_legacy_flag.py
"""

# Standard
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

# Third-Party
from fastapi import APIRouter
import pytest

# First-Party
from tests.helpers.router_helpers import collect_routes

_route_paths = lambda r: [p for p, *_ in collect_routes(r)]  # noqa: E731

# ---------------------------------------------------------------------------
# Helpers (duplicated from test_api_v1.py intentionally — no shared module)
# ---------------------------------------------------------------------------


def _settings(**flags) -> SimpleNamespace:
    """Build a minimal settings-like object."""
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
    r = APIRouter()
    r.add_api_route(sentinel_path, lambda: sentinel_path)
    return r


def _required_kwargs(**extras) -> dict:
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


def _make_mock_router_module(sentinel_path: str) -> ModuleType:
    mod = ModuleType("_mock")
    mod.router = _sentinel_router(sentinel_path)
    return mod


def _make_mock_router_module_named(attr_name: str, sentinel_path: str) -> ModuleType:
    mod = ModuleType("_mock")
    setattr(mod, attr_name, _sentinel_router(sentinel_path))
    return mod


# ---------------------------------------------------------------------------
# Import target
# ---------------------------------------------------------------------------
from mcpgateway.api.v1 import build_legacy_router  # noqa: E402


# ---------------------------------------------------------------------------
# Group A — always-on routers; paths must be at root (no /v1 prefix)
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupA:
    """All required Group A routers are always included WITHOUT /v1 prefix."""

    def test_router_prefix_is_empty(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert v.prefix == ""

    def test_returns_apirouter_instance(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert isinstance(v, APIRouter)

    def test_protocol_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-protocol" in _route_paths(v)
        assert "/v1/sentinel-protocol" not in _route_paths(v)

    def test_tool_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-tool" in _route_paths(v)

    def test_resource_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-resource" in _route_paths(v)

    def test_prompt_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-prompt" in _route_paths(v)

    def test_gateway_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-gateway" in _route_paths(v)

    def test_root_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-root" in _route_paths(v)

    def test_server_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-server" in _route_paths(v)

    def test_metrics_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-metrics" in _route_paths(v)

    def test_tag_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-tag" in _route_paths(v)

    def test_export_import_router_at_root(self):
        v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-export" in _route_paths(v)


# ---------------------------------------------------------------------------
# Group B — tool_plugin_bindings (ImportError tolerance)
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupB:
    """tool_plugin_bindings router included when importable, skipped on ImportError."""

    def test_tool_plugin_bindings_included_when_importable(self):
        mock_mod = _make_mock_router_module("/sentinel-tool-plugin")
        with patch.dict(sys.modules, {"mcpgateway.routers.tool_plugin_bindings": mock_mod}):
            v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-tool-plugin" in _route_paths(v)

    def test_tool_plugin_bindings_import_error_gracefully_skipped(self):
        with patch.dict(sys.modules, {"mcpgateway.routers.tool_plugin_bindings": None}):
            v = build_legacy_router(_settings(), **_required_kwargs())
        assert "/sentinel-protocol" in _route_paths(v)


# ---------------------------------------------------------------------------
# Group C — feature-flagged optional routers
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupC:
    """Feature flags gate optional routers identically to build_v1_router."""

    def test_a2a_router_included_when_enabled(self):
        v = build_legacy_router(_settings(mcpgateway_a2a_enabled=True), **_required_kwargs())
        assert "/sentinel-a2a" in _route_paths(v)

    def test_a2a_router_excluded_when_disabled(self):
        v = build_legacy_router(_settings(mcpgateway_a2a_enabled=False), **_required_kwargs())
        assert "/sentinel-a2a" not in _route_paths(v)

    def test_observability_router_included_when_enabled(self):
        mock_mod = _make_mock_router_module("/sentinel-observability")
        with patch.dict(sys.modules, {"mcpgateway.routers.observability": mock_mod}):
            v = build_legacy_router(_settings(observability_enabled=True), **_required_kwargs())
        assert "/sentinel-observability" in _route_paths(v)

    def test_observability_router_excluded_when_disabled(self):
        mock_mod = _make_mock_router_module("/sentinel-observability")
        with patch.dict(sys.modules, {"mcpgateway.routers.observability": mock_mod}):
            v = build_legacy_router(_settings(observability_enabled=False), **_required_kwargs())
        assert "/sentinel-observability" not in _route_paths(v)

    def test_reverse_proxy_router_included_when_enabled(self):
        mock_mod = _make_mock_router_module("/sentinel-reverse-proxy")
        with patch.dict(sys.modules, {"mcpgateway.routers.reverse_proxy": mock_mod}):
            v = build_legacy_router(_settings(mcpgateway_reverse_proxy_enabled=True), **_required_kwargs())
        assert "/sentinel-reverse-proxy" in _route_paths(v)

    def test_reverse_proxy_router_excluded_when_disabled(self):
        mock_mod = _make_mock_router_module("/sentinel-reverse-proxy")
        with patch.dict(sys.modules, {"mcpgateway.routers.reverse_proxy": mock_mod}):
            v = build_legacy_router(_settings(mcpgateway_reverse_proxy_enabled=False), **_required_kwargs())
        assert "/sentinel-reverse-proxy" not in _route_paths(v)

    def test_cancellation_router_included_when_enabled(self):
        mock_mod = _make_mock_router_module("/sentinel-cancellation")
        with patch.dict(sys.modules, {"mcpgateway.routers.cancellation_router": mock_mod}):
            v = build_legacy_router(_settings(mcpgateway_tool_cancellation_enabled=True), **_required_kwargs())
        assert "/sentinel-cancellation" in _route_paths(v)

    def test_cancellation_router_excluded_when_disabled(self):
        mock_mod = _make_mock_router_module("/sentinel-cancellation")
        with patch.dict(sys.modules, {"mcpgateway.routers.cancellation_router": mock_mod}):
            v = build_legacy_router(_settings(mcpgateway_tool_cancellation_enabled=False), **_required_kwargs())
        assert "/sentinel-cancellation" not in _route_paths(v)

    def test_toolops_router_included_when_enabled(self):
        mock_mod = _make_mock_router_module_named("toolops_router", "/sentinel-toolops")
        with patch.dict(sys.modules, {"mcpgateway.routers.toolops_router": mock_mod}):
            v = build_legacy_router(_settings(toolops_enabled=True), **_required_kwargs())
        assert "/sentinel-toolops" in _route_paths(v)

    def test_toolops_router_excluded_when_disabled(self):
        mock_mod = _make_mock_router_module_named("toolops_router", "/sentinel-toolops")
        with patch.dict(sys.modules, {"mcpgateway.routers.toolops_router": mock_mod}):
            v = build_legacy_router(_settings(toolops_enabled=False), **_required_kwargs())
        assert "/sentinel-toolops" not in _route_paths(v)


# ---------------------------------------------------------------------------
# Group D — auth cluster
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupD:
    """Auth/teams/tokens/RBAC cluster gated on email_auth_enabled."""

    def _auth_modules(self) -> dict:
        return {
            "mcpgateway.routers.auth": _make_mock_router_module_named("auth_router", "/sentinel-auth"),
            "mcpgateway.routers.email_auth": _make_mock_router_module_named("email_auth_router", "/sentinel-email-auth"),
            "mcpgateway.routers.teams": _make_mock_router_module_named("teams_router", "/sentinel-teams"),
            "mcpgateway.routers.tokens": _make_mock_router_module("/sentinel-tokens"),
            "mcpgateway.routers.rbac": _make_mock_router_module("/sentinel-rbac"),
            "mcpgateway.routers.sso": _make_mock_router_module_named("sso_router", "/sentinel-sso"),
        }

    def test_auth_cluster_excluded_when_email_auth_disabled(self):
        with patch.dict(sys.modules, self._auth_modules()):
            v = build_legacy_router(_settings(email_auth_enabled=False), **_required_kwargs())
        paths = _route_paths(v)
        assert "/sentinel-auth" not in paths

    def test_auth_router_included_when_email_auth_enabled(self):
        with patch.dict(sys.modules, self._auth_modules()):
            v = build_legacy_router(_settings(email_auth_enabled=True), **_required_kwargs())
        assert "/sentinel-auth" in _route_paths(v)

    def test_sso_router_excluded_when_sso_disabled(self):
        with patch.dict(sys.modules, self._auth_modules()):
            v = build_legacy_router(_settings(email_auth_enabled=True, sso_enabled=False), **_required_kwargs())
        assert "/sentinel-sso" not in _route_paths(v)

    def test_sso_router_included_when_both_enabled(self):
        with patch.dict(sys.modules, self._auth_modules()):
            v = build_legacy_router(_settings(email_auth_enabled=True, sso_enabled=True), **_required_kwargs())
        assert "/sentinel-sso" in _route_paths(v)


# ---------------------------------------------------------------------------
# Group E — LLM cluster
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupE:
    """LLM cluster gated on llmchat_enabled."""

    def _llm_modules(self) -> dict:
        return {
            "mcpgateway.routers.llmchat_router": _make_mock_router_module_named("llmchat_router", "/sentinel-llmchat"),
            "mcpgateway.routers.llm_config_router": _make_mock_router_module_named("llm_config_router", "/sentinel-llm-config"),
            "mcpgateway.routers.llm_admin_router": _make_mock_router_module_named("llm_admin_router", "/sentinel-llm-admin"),
        }

    def test_llm_cluster_excluded_when_disabled(self):
        with patch.dict(sys.modules, self._llm_modules()):
            v = build_legacy_router(_settings(llmchat_enabled=False), **_required_kwargs())
        paths = _route_paths(v)
        assert "/sentinel-llmchat" not in paths

    def test_llm_cluster_included_when_enabled(self):
        with patch.dict(sys.modules, self._llm_modules()):
            v = build_legacy_router(_settings(llmchat_enabled=True), **_required_kwargs())
        assert "/sentinel-llmchat" in _route_paths(v)


# ---------------------------------------------------------------------------
# Group F — admin cluster
# ---------------------------------------------------------------------------


class TestBuildLegacyRouterGroupF:
    """Admin cluster gated on mcpgateway_admin_api_enabled."""

    def _admin_modules(self) -> dict:
        admin_mod = ModuleType("_admin_mock")
        admin_mod.admin_router = _sentinel_router("/sentinel-admin")
        admin_mod.set_logging_service = lambda _: None
        admin_mod.validate_section_permissions = lambda _: None

        runtime_mod = _make_mock_router_module_named("runtime_admin_router", "/sentinel-runtime-admin")
        well_known_mod = _make_mock_router_module("/sentinel-well-known")
        return {
            "mcpgateway.admin": admin_mod,
            "mcpgateway.routers.runtime_admin_router": runtime_mod,
            "mcpgateway.routers.well_known": well_known_mod,
        }

    def test_admin_cluster_excluded_when_disabled(self):
        with patch.dict(sys.modules, self._admin_modules()):
            v = build_legacy_router(_settings(mcpgateway_admin_api_enabled=False), **_required_kwargs())
        assert "/sentinel-admin" not in _route_paths(v)

    def test_admin_cluster_included_when_enabled(self):
        with patch.dict(sys.modules, self._admin_modules()):
            v = build_legacy_router(_settings(mcpgateway_admin_api_enabled=True), **_required_kwargs())
        assert "/sentinel-admin" in _route_paths(v)
