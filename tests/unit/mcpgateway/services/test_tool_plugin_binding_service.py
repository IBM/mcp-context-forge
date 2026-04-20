# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_plugin_binding_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Madhumohan Jaishankar

Unit tests for ToolPluginBindingService.

Tests cover:
    - _to_response: ORM → Pydantic conversion helper
    - upsert_bindings: insert path, update path, multi-team, multi-tool
    - list_bindings: unfiltered and team-filtered
    - delete_binding: success and not-found error
"""

# Standard
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, ToolPluginBinding
from mcpgateway.schemas import (
    PluginBindingMode,
    PluginPolicyItem,
    TeamPolicies,
    ToolPluginBindingRequest,
    ToolPluginBindingResponse,
)
from mcpgateway.services.tool_plugin_binding_service import (
    ToolPluginBindingNotFoundError,
    ToolPluginBindingService,
    get_bindings_for_tool,
)


# ---------------------------------------------------------------------------
# Canonical "full" config dicts
#
# The PluginPolicyItem validator requires every schema field to be explicitly
# present in the config dict (so callers are aware of all available knobs).
# Use these module-level constants instead of inline partial dicts.
# ---------------------------------------------------------------------------

_OLG: dict = {
    "min_chars": 0,
    "max_chars": 2000,
    "min_tokens": 0,
    "max_tokens": None,
    "chars_per_token": 4,
    "limit_mode": "character",
    "strategy": "truncate",
    "ellipsis": "\u2026",
    "word_boundary": False,
    "max_text_length": 1_000_000,
    "max_structure_size": 10_000,
    "max_recursion_depth": 100,
}

_RL: dict = {
    "by_user": None,
    "by_tenant": None,
    "by_tool": None,
    "algorithm": "fixed_window",
    "backend": "memory",
    "redis_url": None,
    "redis_key_prefix": "rl",
    "redis_fallback": True,
}

_SD: dict = {
    "enabled": {},
    "redact": True,
    "redaction_text": "[REDACTED]",
    "block_on_detection": False,
    "min_findings_to_block": 1,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_binding(
    id_="binding-001",
    team_id="team-a",
    tool_name="tool_x",
    plugin_id="OutputLengthGuardPlugin",
    mode="enforce",
    priority=50,
    config=None,
    binding_reference_id=None,
    created_by="admin@example.com",
    updated_by="admin@example.com",
):
    """Build a MagicMock that quacks like a ToolPluginBinding ORM row."""
    b = MagicMock()
    b.id = id_
    b.team_id = team_id
    b.tool_name = tool_name
    b.plugin_id = plugin_id
    b.mode = mode
    b.priority = priority
    b.config = config if config is not None else dict(_OLG)
    b.binding_reference_id = binding_reference_id
    b.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    b.created_by = created_by
    b.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    b.updated_by = updated_by
    return b


@pytest.fixture
def service():
    """Return a fresh service instance."""
    return ToolPluginBindingService()


@pytest.fixture
def db_session():
    """In-memory SQLite session backed by all ORM models.

    Uses StaticPool so the same in-memory database is shared across all
    connections within the test, giving the service the same view of rows
    it just inserted.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def simple_request():
    """Minimal single-team single-tool POST payload."""
    return ToolPluginBindingRequest(
        teams={
            "team-a": TeamPolicies(
                policies=[
                    PluginPolicyItem(
                        tool_names=["tool_x"],
                        plugin_id="OutputLengthGuardPlugin",
                        mode=PluginBindingMode.ENFORCE,
                        priority=50,
                        config=dict(_OLG),
                    )
                ]
            )
        }
    )


# ---------------------------------------------------------------------------
# _to_response tests
# ---------------------------------------------------------------------------


class TestToResponse:
    """Tests for ToolPluginBindingService._to_response."""

    def test_to_response_fields(self, service):
        """All ORM fields are mapped correctly to the response schema."""
        binding = _make_binding()
        result = service._to_response(binding)

        assert isinstance(result, ToolPluginBindingResponse)
        assert result.id == binding.id
        assert result.team_id == binding.team_id
        assert result.tool_name == binding.tool_name
        assert result.plugin_id == binding.plugin_id
        assert result.mode == binding.mode
        assert result.priority == binding.priority
        assert result.config == binding.config
        assert result.binding_reference_id == binding.binding_reference_id
        assert result.created_at == binding.created_at
        assert result.created_by == binding.created_by
        assert result.updated_at == binding.updated_at
        assert result.updated_by == binding.updated_by


# ---------------------------------------------------------------------------
# upsert_bindings tests
# ---------------------------------------------------------------------------


class TestUpsertBindings:
    """Tests for ToolPluginBindingService.upsert_bindings against a real in-memory SQLite DB."""

    def test_insert_new_binding(self, service, db_session, simple_request):
        """A new (team_id, tool_name, plugin_id) triple is persisted and all fields returned."""
        results = service.upsert_bindings(db_session, simple_request, caller_email="admin@example.com")

        assert len(results) == 1
        r = results[0]
        assert r.team_id == "team-a"
        assert r.tool_name == "tool_x"
        assert r.plugin_id == "OutputLengthGuardPlugin"
        assert r.mode == "enforce"
        assert r.priority == 50
        assert r.config == dict(_OLG)
        assert r.created_by == "admin@example.com"
        assert r.updated_by == "admin@example.com"

        # Verify the row was actually persisted in the DB
        row = db_session.query(ToolPluginBinding).one()
        assert row.tool_name == "tool_x"
        assert row.team_id == "team-a"

    def test_update_existing_binding(self, service, db_session):
        """Re-upserting the same triple updates mutable fields; id and created_by are preserved."""
        cfg_v1 = {**_OLG, "max_chars": 500, "strategy": "truncate"}
        cfg_v2 = {**_OLG, "max_chars": 2000, "strategy": "block"}

        request_v1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=10,
                            config=cfg_v1,
                        )
                    ]
                )
            }
        )
        inserted = service.upsert_bindings(db_session, request_v1, caller_email="creator@example.com")
        original_id = inserted[0].id

        request_v2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,
                            priority=50,
                            config=cfg_v2,
                        )
                    ]
                )
            }
        )
        updated = service.upsert_bindings(db_session, request_v2, caller_email="updater@example.com")

        assert db_session.query(ToolPluginBinding).count() == 1  # still one row

        r = updated[0]
        assert r.id == original_id                       # primary key preserved
        assert r.mode == "enforce"
        assert r.priority == 50
        assert r.config == cfg_v2
        assert r.updated_by == "updater@example.com"
        assert r.created_by == "creator@example.com"     # creation author unchanged

    def test_config_is_fully_replaced_not_merged(self, service, db_session):
        """On update, config is entirely replaced — values absent from the new payload do not survive."""
        cfg_v1 = {**_RL, "by_user": "10/s", "by_tenant": None}
        cfg_v2 = {**_RL, "by_user": None, "by_tenant": "600/m"}

        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id="RateLimiterPlugin", config=cfg_v1)]
                )
            }
        )
        service.upsert_bindings(db_session, r1, caller_email="admin@example.com")

        r2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id="RateLimiterPlugin", config=cfg_v2)]
                )
            }
        )
        results = service.upsert_bindings(db_session, r2, caller_email="admin@example.com")

        assert results[0].config == cfg_v2
        assert results[0].config["by_user"] is None  # original "10/s" is gone

    def test_multiple_tool_names_in_one_policy(self, service, db_session):
        """A policy with multiple tool_names produces one binding per tool, each with the full config."""
        cfg = {**_RL, "by_user": "60/m", "by_tenant": "600/m"}
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id="RateLimiterPlugin",
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=20,
                            config=cfg,
                        )
                    ]
                )
            }
        )
        results = service.upsert_bindings(db_session, request, caller_email="admin@example.com")

        assert len(results) == 2
        assert db_session.query(ToolPluginBinding).count() == 2

        by_tool = {r.tool_name: r for r in results}
        assert set(by_tool.keys()) == {"tool_a", "tool_b"}

        tool_a = by_tool["tool_a"]
        assert tool_a.team_id == "team-a"
        assert tool_a.plugin_id == "RateLimiterPlugin"
        assert tool_a.mode == "permissive"
        assert tool_a.priority == 20
        assert tool_a.config == cfg

        tool_b = by_tool["tool_b"]
        assert tool_b.team_id == "team-a"
        assert tool_b.plugin_id == "RateLimiterPlugin"
        assert tool_b.mode == "permissive"
        assert tool_b.priority == 20
        assert tool_b.config == cfg

    def test_multiple_teams(self, service, db_session):
        """A request spanning two teams produces one binding per team."""
        cfg_olg = {**_OLG, "max_chars": 500, "strategy": "block"}
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id="OutputLengthGuardPlugin", config=cfg_olg)]
                ),
                "team-b": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_y"], plugin_id="SecretsDetection", config=dict(_SD))]
                ),
            }
        )
        results = service.upsert_bindings(db_session, request, caller_email="admin@example.com")

        assert len(results) == 2
        assert db_session.query(ToolPluginBinding).count() == 2

        by_team = {r.team_id: r for r in results}
        assert set(by_team.keys()) == {"team-a", "team-b"}

        team_a = by_team["team-a"]
        assert team_a.tool_name == "tool_x"
        assert team_a.plugin_id == "OutputLengthGuardPlugin"
        assert team_a.config == cfg_olg

        team_b = by_team["team-b"]
        assert team_b.tool_name == "tool_y"
        assert team_b.plugin_id == "SecretsDetection"
        assert team_b.config == dict(_SD)

    def test_caller_email_stored_in_audit_fields(self, service, db_session, simple_request):
        """caller_email is written to both created_by and updated_by on insert."""
        results = service.upsert_bindings(db_session, simple_request, caller_email="admin@example.com")

        assert results[0].created_by == "admin@example.com"
        assert results[0].updated_by == "admin@example.com"

    def test_binding_reference_id_persisted(self, service, db_session):
        """binding_reference_id is stored in the DB and returned in the response."""
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="test-bind-001",
                        )
                    ]
                )
            }
        )
        results = service.upsert_bindings(db_session, request, caller_email="admin@example.com")

        assert results[0].binding_reference_id == "test-bind-001"

        row = db_session.query(ToolPluginBinding).one()
        assert row.binding_reference_id == "test-bind-001"

    def test_ownership_transfer_logs_warning(self, service, db_session, caplog):
        """Upserting the same (team, tool, plugin) triple with a different binding_reference_id
        logs a WARNING and the new reference_id wins."""
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="test-bind-old",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r1, caller_email="admin@example.com")

        r2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="test-bind-new",
                        )
                    ]
                )
            }
        )
        with caplog.at_level(logging.WARNING):
            results = service.upsert_bindings(db_session, r2, caller_email="admin@example.com")

        # New reference wins
        assert results[0].binding_reference_id == "test-bind-new"
        # Warning was emitted
        assert any("ownership transfer" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# list_bindings tests
# ---------------------------------------------------------------------------


class TestListBindings:
    """Tests for ToolPluginBindingService.list_bindings against a real in-memory SQLite DB."""

    @pytest.fixture(autouse=True)
    def seed(self, service, db_session):
        """Insert two bindings for different teams before each test."""
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id="RateLimiterPlugin", config=dict(_RL))]),
                "team-b": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_y"], plugin_id="SecretsDetection", config=dict(_SD))]),
            }
        )
        service.upsert_bindings(db_session, request, caller_email="seeder@example.com")

    def test_list_all_no_filter(self, service, db_session):
        """team_id=None returns all bindings from all teams."""
        results = service.list_bindings(db_session, team_id=None)
        assert len(results) == 2
        assert {r.team_id for r in results} == {"team-a", "team-b"}

    def test_list_with_team_filter(self, service, db_session):
        """team_id filter returns only bindings for that team."""
        results = service.list_bindings(db_session, team_id="team-a")
        assert len(results) == 1
        assert results[0].team_id == "team-a"

    def test_list_ordered_by_priority(self, service, db_session):
        """Results are returned in ascending priority order within a team."""
        # Add a second binding for team-a with a lower priority number (runs first)
        r = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_z"], plugin_id="OutputLengthGuardPlugin", priority=10, config={**_OLG, "max_chars": 500, "strategy": "block"})]
                )
            }
        )
        service.upsert_bindings(db_session, r, caller_email="admin@example.com")

        results = service.list_bindings(db_session, team_id="team-a")
        assert len(results) == 2
        priorities = [r.priority for r in results]
        assert priorities == sorted(priorities)

    def test_list_empty(self, service, db_session):
        """Returns empty list when no bindings exist for the specified team."""
        results = service.list_bindings(db_session, team_id="team-unknown")
        assert results == []


# ---------------------------------------------------------------------------
# delete_binding tests
# ---------------------------------------------------------------------------


class TestDeleteBinding:
    """Tests for ToolPluginBindingService.delete_binding against a real in-memory SQLite DB."""

    def test_delete_success(self, service, db_session):
        """delete_binding returns the deleted record's details and removes it from the DB."""
        r = ToolPluginBindingRequest(
            teams={"team-a": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id="RateLimiterPlugin", config=dict(_RL))])}
        )
        inserted = service.upsert_bindings(db_session, r, caller_email="admin@example.com")
        binding_id = inserted[0].id

        deleted = service.delete_binding(db_session, binding_id)

        assert deleted.id == binding_id
        assert deleted.team_id == "team-a"
        assert deleted.tool_name == "tool_x"
        assert deleted.plugin_id == "RateLimiterPlugin"
        assert deleted.config == dict(_RL)
        # Confirm the row is gone from the DB
        assert db_session.query(ToolPluginBinding).filter_by(id=binding_id).first() is None

    def test_delete_not_found(self, service, db_session):
        """delete_binding raises ToolPluginBindingNotFoundError for an unknown ID."""
        with pytest.raises(ToolPluginBindingNotFoundError, match="not found"):
            service.delete_binding(db_session, "nonexistent-id")


# ---------------------------------------------------------------------------
# Schema validation tests — PluginPolicyItem cross-validation
# ---------------------------------------------------------------------------


class TestPluginPolicyItemValidation:
    """Tests for PluginPolicyItem including config cross-validation per plugin."""

    def test_defaults_mode_and_priority(self):
        """PluginPolicyItem defaults for mode and priority; RATE_LIMITER full config is accepted."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id="RateLimiterPlugin",
            config=dict(_RL),
        )
        assert item.mode == PluginBindingMode.ENFORCE
        assert item.priority == 50

    def test_output_length_guard_valid_config(self):
        """OUTPUT_LENGTH_GUARD with all fields is accepted by PluginPolicyItem."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id="OutputLengthGuardPlugin",
            config={**_OLG, "max_chars": 500, "strategy": "block"},
        )
        assert item.plugin_id == "OutputLengthGuardPlugin"

    def test_output_length_guard_empty_config_accepted(self):
        """OUTPUT_LENGTH_GUARD with {} is accepted — CF does not validate config fields."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id="OutputLengthGuardPlugin",
            config={},
        )
        assert item.plugin_id == "OutputLengthGuardPlugin"

    def test_rate_limiter_valid_config(self):
        """RATE_LIMITER with full config is accepted by PluginPolicyItem."""
        item = PluginPolicyItem(
            tool_names=["tool_y"],
            plugin_id="RateLimiterPlugin",
            config={**_RL, "by_user": "60/m", "by_tenant": "600/m"},
        )
        assert item.plugin_id == "RateLimiterPlugin"

    def test_secrets_detection_valid_config(self):
        """SECRETS_DETECTION with all required fields is accepted by PluginPolicyItem."""
        item = PluginPolicyItem(
            tool_names=["tool_z"],
            plugin_id="SecretsDetection",
            config={"enabled": {"aws_key": True}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": True, "min_findings_to_block": 2},
        )
        assert item.plugin_id == "SecretsDetection"

    def test_secrets_detection_empty_config_accepted(self):
        """SECRETS_DETECTION with {} is accepted — CF does not validate config fields."""
        item = PluginPolicyItem(
            tool_names=["tool_z"],
            plugin_id="SecretsDetection",
            config={},
        )
        assert item.plugin_id == "SecretsDetection"

    def test_empty_tool_names_rejected(self):
        """tool_names=[] is rejected (min_length=1)."""
        with pytest.raises(ValidationError, match=r"(?s)tool_names.*at least 1 item"):
            PluginPolicyItem(
                tool_names=[],
                plugin_id="RateLimiterPlugin",
                config={"by_user": None, "by_tenant": None, "by_tool": None},
            )

    def test_priority_below_minimum_rejected(self):
        """priority=0 is rejected (ge=1)."""
        with pytest.raises(ValidationError, match=r"(?s)priority.*greater than or equal to 1"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="RateLimiterPlugin",
                priority=0,
                config=dict(_RL),
            )

    def test_priority_above_maximum_rejected(self):
        """priority=1001 is rejected (le=1000)."""
        with pytest.raises(ValidationError, match=r"(?s)priority.*less than or equal to 1000"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="RateLimiterPlugin",
                priority=1001,
                config=dict(_RL),
            )

    def test_binding_reference_id_accepted(self):
        """binding_reference_id is optional and stored when provided."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id="OutputLengthGuardPlugin",
            config=dict(_OLG),
            binding_reference_id="test-bind-001",
        )
        assert item.binding_reference_id == "test-bind-001"

    def test_binding_reference_id_defaults_to_none(self):
        """binding_reference_id is None when not specified."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id="OutputLengthGuardPlugin",
            config=dict(_OLG),
        )
        assert item.binding_reference_id is None

    def test_binding_reference_id_max_length(self):
        """binding_reference_id longer than 255 characters is rejected (matches DB column limit)."""
        with pytest.raises(ValidationError):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="OutputLengthGuardPlugin",
                config=dict(_OLG),
                binding_reference_id="a" * 256,
            )

    def test_extra_fields_forbidden(self):
        """Unknown fields on PluginPolicyItem are rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="RateLimiterPlugin",
                config={"by_user": None, "by_tenant": None, "by_tool": None},
                unknown_key="bad",
            )

    def test_config_field_is_required(self):
        """config is a required field — omitting it is rejected at schema validation time."""
        with pytest.raises(ValidationError, match=r"(?s)config.*Field required"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="RateLimiterPlugin",
                # config intentionally omitted
            )

# ---------------------------------------------------------------------------
# Schema validation tests — top-level request/enum invariants
# ---------------------------------------------------------------------------


class TestTopLevelSchemas:
    """Tests for ToolPluginBindingRequest, TeamPolicies, and enum values."""

    def test_request_requires_at_least_one_team(self):
        """ToolPluginBindingRequest with empty teams dict is rejected."""
        with pytest.raises(ValidationError, match=r"(?s)teams.*at least 1 item"):
            ToolPluginBindingRequest(teams={})

    def test_team_policies_requires_at_least_one_policy(self):
        """TeamPolicies with an empty policies list is rejected."""
        with pytest.raises(ValidationError, match=r"(?s)policies.*at least 1 item"):
            TeamPolicies(policies=[])

    def test_plugin_binding_mode_enum_values(self):
        """PluginBindingMode enum covers all expected execution modes."""
        assert PluginBindingMode.ENFORCE == "enforce"
        assert PluginBindingMode.PERMISSIVE == "permissive"
        assert PluginBindingMode.DISABLED == "disabled"


# ---------------------------------------------------------------------------
# get_bindings_for_tool tests
# ---------------------------------------------------------------------------


class TestGetBindingsForTool:
    """Tests for the module-level get_bindings_for_tool() query function."""

    @pytest.fixture(autouse=True)
    def _seed(self, service, db_session):
        """Insert a known set of bindings used across tests."""
        self._service = service
        self._db = db_session

        # Exact binding for (team-a, tool_x) — OUTPUT_LENGTH_GUARD
        olg_req = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,
                            priority=50,
                            config=dict(_OLG),
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, olg_req, caller_email="admin@example.com")

        # Wildcard binding for (team-a, *) — RATE_LIMITER
        rl_req = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["*"],
                            plugin_id="RateLimiterPlugin",
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=10,
                            config={**_RL, "by_user": "100/m", "by_tenant": "1000/m"},
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, rl_req, caller_email="admin@example.com")

    def test_returns_exact_and_wildcard_bindings(self):
        """get_bindings_for_tool returns both the exact tool_name match and the '*' wildcard."""
        results = get_bindings_for_tool(self._db, "team-a", "tool_x")
        plugin_ids = {b.plugin_id for b in results}
        assert plugin_ids == {"OutputLengthGuardPlugin", "RateLimiterPlugin"}

    def test_returns_only_wildcard_for_unknown_tool(self):
        """A tool with no exact binding still gets the wildcard binding."""
        results = get_bindings_for_tool(self._db, "team-a", "other_tool")
        assert len(results) == 1
        assert results[0].plugin_id == "RateLimiterPlugin"

    def test_returns_empty_for_unknown_team(self):
        """An unknown team has no bindings."""
        results = get_bindings_for_tool(self._db, "unknown-team", "tool_x")
        assert results == []

    def test_exact_overrides_wildcard_for_same_plugin(self, service, db_session):
        """When both an exact and a wildcard binding exist for the same plugin_id,
        the exact (more specific) binding wins regardless of insertion order."""
        # Insert a wildcard OUTPUT_LENGTH_GUARD first
        wc_req = ToolPluginBindingRequest(
            teams={
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["*"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=1,
                            config={**_OLG, "max_chars": 100},
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, wc_req, caller_email="admin@example.com")

        # Now insert an exact OUTPUT_LENGTH_GUARD for team-b/tool_z
        exact_req = ToolPluginBindingRequest(
            teams={
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_z"],
                            plugin_id="OutputLengthGuardPlugin",
                            mode=PluginBindingMode.ENFORCE,
                            priority=99,
                            config={**_OLG, "max_chars": 9999},
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, exact_req, caller_email="admin@example.com")

        results = get_bindings_for_tool(db_session, "team-b", "tool_z")
        # Specificity wins: exact tool_name binding always beats the '*' wildcard
        olg_results = [b for b in results if b.plugin_id == "OutputLengthGuardPlugin"]
        assert len(olg_results) == 1
        # The exact binding (priority=99, max_chars=9999) wins — not the wildcard (priority=1, max_chars=100)
        assert olg_results[0].priority == 99

    def test_does_not_cross_team_boundaries(self):
        """Bindings for a different team are not returned."""
        results = get_bindings_for_tool(self._db, "team-b", "tool_x")
        assert results == []


# ---------------------------------------------------------------------------
# Stale-tool pruning tests
# ---------------------------------------------------------------------------


class TestStalePruning:
    """Tests for the stale-tool pruning logic in upsert_bindings.

    When an upsert includes a binding_reference_id, any existing binding
    that shares the same (binding_reference_id, plugin_id) pair but whose
    tool_name is absent from the incoming list is automatically deleted.
    """

    def test_stale_tools_pruned_when_binding_reference_id_present(self, service, db_session):
        """Tools removed from the incoming list are deleted when binding_reference_id is set."""
        # Initial upsert: bind ref-001 to tool_a, tool_b, tool_c
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b", "tool_c"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-001",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r1, caller_email="admin@example.com")
        assert db_session.query(ToolPluginBinding).count() == 3

        # Second upsert: ref-001 now only covers tool_a and tool_b — tool_c is stale
        r2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-001",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r2, caller_email="admin@example.com")

        remaining = db_session.query(ToolPluginBinding).all()
        assert len(remaining) == 2
        tool_names = {b.tool_name for b in remaining}
        assert tool_names == {"tool_a", "tool_b"}

    def test_tools_in_incoming_list_are_preserved(self, service, db_session):
        """Tools that are still in the incoming list are NOT pruned."""
        r = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-002",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r, caller_email="admin@example.com")

        # Upsert again with the same list — nothing should be pruned
        service.upsert_bindings(db_session, r, caller_email="admin@example.com")

        assert db_session.query(ToolPluginBinding).count() == 2

    def test_no_pruning_when_binding_reference_id_is_none(self, service, db_session):
        """Bindings without a binding_reference_id are never pruned by subsequent upserts."""
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            # intentionally no binding_reference_id
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r1, caller_email="admin@example.com")

        # Second upsert — same plugin, no reference ID, reduced tool list
        r2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r2, caller_email="admin@example.com")

        # tool_b must NOT be pruned because no binding_reference_id was supplied
        assert db_session.query(ToolPluginBinding).count() == 2

    def test_pruning_only_affects_matching_ref_and_plugin(self, service, db_session):
        """Pruning is scoped to (binding_reference_id, plugin_id) — other refs/plugins are untouched."""
        # ref-A binds OLG to tool_a and tool_b
        r_a = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-A",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r_a, caller_email="admin@example.com")

        # ref-B binds RL to tool_c
        r_b = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_c"],
                            plugin_id="RateLimiterPlugin",
                            config=dict(_RL),
                            binding_reference_id="ref-B",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r_b, caller_email="admin@example.com")

        assert db_session.query(ToolPluginBinding).count() == 3

        # Update ref-A/OLG to only cover tool_a — tool_b should be pruned
        r_a_updated = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-A",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r_a_updated, caller_email="admin@example.com")

        remaining = db_session.query(ToolPluginBinding).all()
        assert len(remaining) == 2
        tool_names = {b.tool_name for b in remaining}
        # tool_b pruned; tool_a (ref-A/OLG) and tool_c (ref-B/RL) survive
        assert tool_names == {"tool_a", "tool_c"}

    def test_multiple_reference_ids_pruned_independently(self, service, db_session):
        """A single upsert containing multiple reference IDs prunes each independently."""
        # Seed: ref-X owns tool_1, tool_2; ref-Y owns tool_3, tool_4
        seed = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_1", "tool_2"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-X",
                        ),
                        PluginPolicyItem(
                            tool_names=["tool_3", "tool_4"],
                            plugin_id="RateLimiterPlugin",
                            config=dict(_RL),
                            binding_reference_id="ref-Y",
                        ),
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, seed, caller_email="admin@example.com")
        assert db_session.query(ToolPluginBinding).count() == 4

        # Update: ref-X shrinks to tool_1 only; ref-Y shrinks to tool_3 only
        update = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_1"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-X",
                        ),
                        PluginPolicyItem(
                            tool_names=["tool_3"],
                            plugin_id="RateLimiterPlugin",
                            config=dict(_RL),
                            binding_reference_id="ref-Y",
                        ),
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, update, caller_email="admin@example.com")

        remaining = db_session.query(ToolPluginBinding).all()
        assert len(remaining) == 2
        assert {b.tool_name for b in remaining} == {"tool_1", "tool_3"}


# ---------------------------------------------------------------------------
# list_bindings — binding_reference_id filter tests
# ---------------------------------------------------------------------------


class TestListBindingsByReference:
    """Tests for list_bindings filtering by binding_reference_id."""

    def test_filter_by_binding_reference_id(self, service, db_session):
        """list_bindings with binding_reference_id returns only matching bindings."""
        r = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="ref-filter-001",
                        )
                    ]
                ),
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_y"],
                            plugin_id="RateLimiterPlugin",
                            config=dict(_RL),
                            binding_reference_id="ref-filter-002",
                        )
                    ]
                ),
            }
        )
        service.upsert_bindings(db_session, r, caller_email="admin@example.com")

        results = service.list_bindings(db_session, binding_reference_id="ref-filter-001")
        assert len(results) == 1
        assert results[0].binding_reference_id == "ref-filter-001"
        assert results[0].team_id == "team-a"

    def test_binding_reference_id_takes_precedence_over_team_id(self, service, db_session, caplog):
        """When both team_id and binding_reference_id are provided, reference ID wins and a warning is logged."""
        r = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id="OutputLengthGuardPlugin",
                            config=dict(_OLG),
                            binding_reference_id="unique-ref",
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, r, caller_email="admin@example.com")

        # Supply team_id="team-b" (which has no bindings) but binding_reference_id
        # for team-a's binding — reference ID takes precedence and a warning is emitted.
        with caplog.at_level(logging.WARNING):
            results = service.list_bindings(db_session, team_id="team-b", binding_reference_id="unique-ref")
        assert len(results) == 1
        assert results[0].team_id == "team-a"
        expected_warning = (
            "Both team_id='team-b' and binding_reference_id='unique-ref' supplied to list_bindings; "
            "team_id will be ignored. Omit team_id when filtering by binding_reference_id."
        )
        assert expected_warning in caplog.messages, (
            f"Expected warning not found. Got: {caplog.messages}"
        )

    def test_filter_by_reference_id_no_match_returns_empty(self, service, db_session):
        """list_bindings with a non-existent binding_reference_id returns an empty list."""
        results = service.list_bindings(db_session, binding_reference_id="does-not-exist")
        assert results == []


class TestGetBindingsForToolUsesName:
    """get_bindings_for_tool must match on tool name (team-scoped unique identifier),
    not original_name (which is only unique per gateway).

    Two gateways in the same team can each expose a tool with the same original_name
    (e.g. "fetch_data"). The DB-level unique identifier for a tool is its `name` column,
    enforced by constraint uq_team_owner_email_name_tool. Bindings must therefore be
    keyed on `name` (e.g. "alpha-gw-fetch-data") to remain unambiguous.
    """

    def test_binding_stored_with_name_is_found_by_name(self, db_session):
        """A binding stored with tool_name='alpha-gw-fetch-data' is retrieved when
        queried with that exact name, and every stored field is returned intact."""
        db_session.add(
            ToolPluginBinding(
                id="b-001",
                team_id="team-abc",
                tool_name="alpha-gw-fetch-data",
                plugin_id="OutputLengthGuardPlugin",
                mode="enforce",
                priority=50,
                config=dict(_OLG),
                created_by="admin@example.com",
                updated_by="admin@example.com",
            )
        )
        db_session.commit()

        results = get_bindings_for_tool(db_session, "team-abc", "alpha-gw-fetch-data")
        assert len(results) == 1
        row = results[0]
        assert row.id == "b-001"
        assert row.team_id == "team-abc"
        assert row.tool_name == "alpha-gw-fetch-data"
        assert row.plugin_id == "OutputLengthGuardPlugin"
        assert row.mode == "enforce"
        assert row.priority == 50
        assert row.config == dict(_OLG)
        assert row.created_by == "admin@example.com"
        assert row.updated_by == "admin@example.com"

    def test_binding_stored_with_name_is_not_found_by_original_name(self, db_session):
        """A binding stored with tool_name='alpha-gw-fetch-data' is NOT returned when
        queried with original_name='fetch_data'. The two are different keys; using
        original_name as the lookup key would silently miss the binding."""
        db_session.add(
            ToolPluginBinding(
                id="b-002",
                team_id="team-abc",
                tool_name="alpha-gw-fetch-data",
                plugin_id="OutputLengthGuardPlugin",
                mode="enforce",
                priority=50,
                config=dict(_OLG),
                created_by="admin@example.com",
                updated_by="admin@example.com",
            )
        )
        db_session.commit()

        # Querying by the bare original_name must return nothing — the team-scoped
        # name ("alpha-gw-fetch-data") is the only valid binding key.
        results = get_bindings_for_tool(db_session, "team-abc", "fetch_data")
        assert results == []
