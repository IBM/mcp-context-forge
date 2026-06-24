# -*- coding: utf-8 -*-
"""
Location: ./tests/unit/plugins/test_security_clearance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Katia Neli

Unit tests for Bell-LaPadula MAC Security Clearance Plugin.
Covers: ClearanceEngine, ClearanceRepository, SecurityClearancePlugin hooks.
"""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPostInvokePayload,
    ResourcePreFetchPayload,
    ResourcePostFetchPayload,
    PromptPrehookPayload,
)

from plugins.security_clearance.security_clearance import (
    ClearanceEngine,
    SecurityClearanceConfig,
    SecurityClearancePlugin,
)
from plugins.security_clearance.repository import ClearanceRepository
from plugins.security_clearance.models import (
    SCUserClearance,
    SCTeamClearance,
    SCToolClassification,
    SCServerClassification,
    SCClearanceAuditLog,
)


def _make_plugin(config: dict = None) -> SecurityClearancePlugin:
    return SecurityClearancePlugin(
        PluginConfig(
            name="test-clearance",
            kind="security_clearance",
            hooks=[],
            mode="enforce",
            priority=5,
            config=config or {},
        )
    )


def _make_context(user: str = "alice", tenant_id: str = "tenant1") -> PluginContext:
    from mcpgateway.plugins.framework import GlobalContext
    gc = GlobalContext(request_id="req-test-123", user=user, tenant_id=tenant_id)
    return PluginContext(global_context=gc)


# Phase 1 — ClearanceEngine unit tests
class TestNoReadUp:
    """No Read Up (Simple Security Property)."""

    def test_allow_equal_level(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_read_up(2, 2) is True

    def test_allow_higher_user(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_read_up(3, 2) is True

    def test_deny_lower_user(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_read_up(1, 3) is False

    def test_deny_public_reading_secret(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_read_up(0, 3) is False


class TestNoWriteDown:
    """No Write Down (Star Property)."""

    def test_allow_equal_level(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_write_down(2, 2) is True

    def test_allow_write_up(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_write_down(1, 3) is True

    def test_deny_write_down(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_no_write_down(3, 1) is False


class TestLateralBands:
    """Lateral communication within security bands."""

    def test_same_band_allowed(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_lateral(0, 1, bands=[[0, 1]]) is True

    def test_different_band_denied(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_lateral(0, 3, bands=[[0, 1], [2, 3]]) is False

    def test_no_bands_same_level(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        assert engine.check_lateral(2, 2, bands=None) is True


class TestResolveUserClearance:
    """User clearance resolution: user -> team -> default."""

    def test_resolve_known_user(self):
        cfg = SecurityClearanceConfig(user_clearances={"alice": 3})
        engine = ClearanceEngine(cfg)
        assert engine.resolve_user_clearance("alice", None) == 3

    def test_resolve_team_fallback(self):
        cfg = SecurityClearanceConfig(team_clearances={"engineering": 2})
        engine = ClearanceEngine(cfg)
        assert engine.resolve_user_clearance("unknown", "engineering") == 2

    def test_resolve_default_fallback(self):
        cfg = SecurityClearanceConfig(default_user_clearance=0)
        engine = ClearanceEngine(cfg)
        assert engine.resolve_user_clearance("nobody", "no-team") == 0

    def test_user_takes_priority_over_team(self):
        cfg = SecurityClearanceConfig(
            user_clearances={"alice": 4},
            team_clearances={"engineering": 2},
        )
        engine = ClearanceEngine(cfg)
        assert engine.resolve_user_clearance("alice", "engineering") == 4


class TestResolveToolLevel:
    """Tool classification resolution: tool -> server -> default."""

    def test_resolve_known_tool(self):
        cfg = SecurityClearanceConfig(tool_levels={"admin-panel": 3})
        engine = ClearanceEngine(cfg)
        assert engine.resolve_tool_level("admin-panel") == 3

    def test_resolve_server_fallback(self):
        cfg = SecurityClearanceConfig(server_levels={"prod-db": 4})
        engine = ClearanceEngine(cfg)
        assert engine.resolve_tool_level("unknown-tool", "prod-db") == 4

    def test_resolve_default_fallback(self):
        cfg = SecurityClearanceConfig(default_tool_classification=1)
        engine = ClearanceEngine(cfg)
        assert engine.resolve_tool_level("unknown", "unknown-server") == 1

    def test_tool_takes_priority_over_server(self):
        cfg = SecurityClearanceConfig(
            tool_levels={"secret-tool": 5},
            server_levels={"prod-db": 4},
        )
        engine = ClearanceEngine(cfg)
        assert engine.resolve_tool_level("secret-tool", "prod-db") == 5


class TestRedaction:
    """Field redaction strategies."""

    def test_redact_strategy(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        data = {"password": "s3cr3t", "name": "alice"}
        result = engine.redact_fields(data, ["password"], "redact")
        assert result["password"] == "[REDACTED]"
        assert result["name"] == "alice"

    def test_remove_strategy(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        data = {"api_key": "abc123", "name": "alice"}
        result = engine.redact_fields(data, ["api_key"], "remove")
        assert "api_key" not in result

    def test_no_redaction_for_unknown_field(self):
        engine = ClearanceEngine(SecurityClearanceConfig())
        data = {"safe_field": "value"}
        result = engine.redact_fields(data, ["password"], "redact")
        assert result["safe_field"] == "value"


# Phase 1 — Plugin hooks tests
class TestToolPreInvokeHook:
    """tool_pre_invoke hook enforcement."""

    @pytest.mark.asyncio
    async def test_allow_sufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 3},
            "tool_levels": {"admin-panel": 2},
            "enforce_no_read_up": True,
        })
        payload = MagicMock(spec=ToolPreInvokePayload)
        payload.tool_name = "admin-panel"
        payload.server_name = None
        payload.arguments = {}
        context = _make_context(user="alice")
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_deny_insufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 1},
            "tool_levels": {"admin-panel": 3},
            "enforce_no_read_up": True,
        })
        payload = MagicMock(spec=ToolPreInvokePayload)
        payload.tool_name = "admin-panel"
        payload.server_name = None
        payload.arguments = {}
        context = _make_context(user="alice")
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.violation is not None
        assert "CLEARANCE" in result.violation.code

    @pytest.mark.asyncio
    async def test_allow_when_enforcement_disabled(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 0},
            "tool_levels": {"admin-panel": 5},
            "enforce_no_read_up": False,
        })
        payload = MagicMock(spec=ToolPreInvokePayload)
        payload.tool_name = "admin-panel"
        payload.server_name = None
        payload.arguments = {}
        context = _make_context(user="alice")
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.violation is None


class TestToolPostInvokeHook:
    """tool_post_invoke hook — No Write Down enforcement."""

    @pytest.mark.asyncio
    async def test_allow_write_same_level(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 2},
            "tool_levels": {"tool-a": 2},
            "enforce_no_write_down": True,
        })
        payload = MagicMock(spec=ToolPostInvokePayload)
        payload.tool_name = "tool-a"
        payload.server_name = None
        payload.result = {"data": "value"}
        context = _make_context(user="alice")
        result = await plugin.tool_post_invoke(payload, context)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_deny_write_down(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 1},
            "tool_levels": {"high-tool": 3},
            "enforce_no_write_down": True,
            "downgrade_rules": {"enable": False},
        })
        payload = MagicMock(spec=ToolPostInvokePayload)
        payload.tool_name = "high-tool"
        payload.server_name = None
        payload.result = {"secret": "data"}
        context = _make_context(user="alice")
        result = await plugin.tool_post_invoke(payload, context)
        assert result.violation is not None


class TestResourcePreFetchHook:
    """resource_pre_fetch hook — No Read Up on resources."""

    @pytest.mark.asyncio
    async def test_allow_sufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 3},
            "enforce_no_read_up": True,
            "default_tool_classification": 1,
        })
        payload = MagicMock(spec=ResourcePreFetchPayload)
        payload.resource_uri = "resource://public-data"
        payload.server_name = None
        context = _make_context(user="alice")
        result = await plugin.resource_pre_fetch(payload, context)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_deny_insufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 0},
            "enforce_no_read_up": True,
            "default_tool_classification": 3,
        })
        payload = MagicMock(spec=ResourcePreFetchPayload)
        payload.resource_uri = "resource://secret-data"
        payload.server_name = None
        context = _make_context(user="alice")
        result = await plugin.resource_pre_fetch(payload, context)
        assert result.violation is not None


class TestResourcePostFetchHook:
    """resource_post_fetch hook — No Write Down on resource content."""

    @pytest.mark.asyncio
    async def test_allow_same_level(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 2},
            "enforce_no_write_down": True,
            "default_tool_classification": 2,
        })
        payload = MagicMock(spec=ResourcePostFetchPayload)
        payload.resource_uri = "resource://data"
        payload.server_name = None
        payload.content = MagicMock()
        payload.content.text = "some content"
        context = _make_context(user="alice")
        result = await plugin.resource_post_fetch(payload, context)
        assert result.violation is None


class TestPromptPreFetchHook:
    """prompt_pre_fetch hook — clearance check on prompts."""

    @pytest.mark.asyncio
    async def test_allow_sufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 3},
            "enforce_no_read_up": True,
            "default_tool_classification": 1,
        })
        payload = MagicMock(spec=PromptPrehookPayload)
        payload.prompt_name = "public-prompt"
        payload.server_name = None
        context = _make_context(user="alice")
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_deny_insufficient_clearance(self):
        plugin = _make_plugin({
            "user_clearances": {"alice": 0},
            "enforce_no_read_up": True,
            "default_tool_classification": 4,
        })
        payload = MagicMock(spec=PromptPrehookPayload)
        payload.prompt_name = "secret-prompt"
        payload.server_name = None
        context = _make_context(user="alice")
        result = await plugin.prompt_pre_fetch(payload, context)
        assert result.violation is not None


# Phase 2 — ClearanceRepository unit tests (with mock DB)
class TestClearanceRepository:
    """ClearanceRepository DB access layer."""

    def _mock_db(self, row=None):
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = row
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = [row] if row else []
        db.query.return_value = q
        return db

    def test_get_user_clearance_found(self):
        row = MagicMock()
        row.clearance_level = 3
        row.expires_at = None
        repo = ClearanceRepository()
        db = self._mock_db(row)
        assert repo.get_user_clearance(db, "alice") == 3

    def test_get_user_clearance_expired(self):
        row = MagicMock()
        row.clearance_level = 3
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        repo = ClearanceRepository()
        db = self._mock_db(row)
        assert repo.get_user_clearance(db, "alice") is None

    def test_get_user_clearance_not_found(self):
        repo = ClearanceRepository()
        db = self._mock_db(None)
        assert repo.get_user_clearance(db, "nobody") is None

    def test_get_team_clearance_found(self):
        row = MagicMock()
        row.clearance_level = 2
        repo = ClearanceRepository()
        db = self._mock_db(row)
        assert repo.get_team_clearance(db, "engineering") == 2

    def test_get_team_clearance_not_found(self):
        repo = ClearanceRepository()
        db = self._mock_db(None)
        assert repo.get_team_clearance(db, "unknown") is None

    def test_get_tool_classification_found(self):
        row = MagicMock()
        row.classification_level = 4
        repo = ClearanceRepository()
        db = self._mock_db(row)
        assert repo.get_tool_classification(db, "admin-panel") == 4

    def test_get_tool_classification_not_found(self):
        repo = ClearanceRepository()
        db = self._mock_db(None)
        assert repo.get_tool_classification(db, "unknown") is None

    def test_get_server_classification_found(self):
        row = MagicMock()
        row.classification_level = 3
        repo = ClearanceRepository()
        db = self._mock_db(row)
        assert repo.get_server_classification(db, "prod-db") == 3

    def test_write_audit_log_success(self):
        repo = ClearanceRepository()
        db = MagicMock()
        repo.write_audit_log(
            db,
            user_id="alice",
            tenant_id="tenant1",
            request_id="req-123",
            user_clearance=2,
            resource_type="tool",
            resource_name="admin-panel",
            resource_level=3,
            decision="DENY",
            violation_type="NO_READ_UP",
            hook="tool_pre_invoke",
        )
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_write_audit_log_rollback_on_error(self):
        repo = ClearanceRepository()
        db = MagicMock()
        db.commit.side_effect = Exception("DB error")
        repo.write_audit_log(
            db,
            user_id="alice",
            tenant_id=None,
            request_id=None,
            user_clearance=0,
            resource_type="tool",
            resource_name="test",
            resource_level=1,
            decision="DENY",
        )
        db.rollback.assert_called_once()

    def test_get_audit_trail_returns_list(self):
        row = MagicMock()
        repo = ClearanceRepository()
        db = self._mock_db(row)
        result = repo.get_audit_trail(db, user_id="alice", decision="DENY")
        assert isinstance(result, list)

    def test_get_audit_trail_db_error_returns_empty(self):
        repo = ClearanceRepository()
        db = MagicMock()
        db.query.side_effect = Exception("DB down")
        result = repo.get_audit_trail(db)
        assert result == []


# Phase 2 — DB-first with YAML fallback integration
class TestDBFirstYAMLFallback:
    """ClearanceEngine uses DB first, falls back to YAML."""

    def test_db_level_overrides_yaml(self):
        cfg = SecurityClearanceConfig(user_clearances={"alice": 1})
        mock_repo = MagicMock()
        mock_repo.get_user_clearance.return_value = 4  # DB says 4
        mock_db = MagicMock()

        with patch("plugins.security_clearance.security_clearance._repo", mock_repo):
            engine = ClearanceEngine(cfg, db=mock_db)
            result = engine.resolve_user_clearance("alice", None)
        assert result == 4  # DB wins over YAML

    def test_yaml_fallback_when_db_returns_none(self):
        cfg = SecurityClearanceConfig(user_clearances={"alice": 2})
        mock_repo = MagicMock()
        mock_repo.get_user_clearance.return_value = None  # DB miss
        mock_repo.get_team_clearance.return_value = None
        mock_db = MagicMock()

        with patch("plugins.security_clearance.security_clearance._repo", mock_repo):
            engine = ClearanceEngine(cfg, db=mock_db)
            result = engine.resolve_user_clearance("alice", None)
        assert result == 2  # YAML fallback

    def test_no_db_uses_yaml_only(self):
        cfg = SecurityClearanceConfig(user_clearances={"alice": 3})
        engine = ClearanceEngine(cfg, db=None)
        assert engine.resolve_user_clearance("alice", None) == 3


# Phase 2 — Repository 
class TestRepositoryResourceAndA2A:
    """Repository lookups for resource and A2A agent clearances."""

    def _mock_db(self, row=None):
        db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = row
        db.query.return_value = q
        return db

    def test_get_resource_classification_found(self):
        from plugins.security_clearance.models import SCResourceClassification
        row = MagicMock()
        row.classification_level = 2
        repo = ClearanceRepository()
        db = self._mock_db(row)
        result = repo.get_tool_classification(db, "resource-uri", None)
        assert result == 2

    def test_get_a2a_agent_clearance_found(self):
        from plugins.security_clearance.models import SCA2AAgentClearance
        row = MagicMock()
        row.clearance_level = 3
        row.expires_at = None
        repo = ClearanceRepository()
        db = self._mock_db(row)
        result = repo.get_user_clearance(db, "agent-001")
        assert result == 3

    def test_get_a2a_agent_clearance_expired(self):
        row = MagicMock()
        row.clearance_level = 3
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        repo = ClearanceRepository()
        db = self._mock_db(row)
        result = repo.get_user_clearance(db, "agent-001")
        assert result is None

    def test_repository_db_exception_returns_none(self):
        repo = ClearanceRepository()
        db = MagicMock()
        db.query.side_effect = Exception("DB down")
        assert repo.get_user_clearance(db, "alice") is None
        assert repo.get_team_clearance(db, "team1") is None
        assert repo.get_tool_classification(db, "tool1") is None
        assert repo.get_server_classification(db, "server1") is None