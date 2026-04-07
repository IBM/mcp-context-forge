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
    OutputLengthGuardConfig,
    PluginBindingMode,
    PluginId,
    PluginPolicyItem,
    RateLimiterConfig,
    SecretsDetectionConfig,
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
# Fixtures
# ---------------------------------------------------------------------------


def _make_binding(
    id_="binding-001",
    team_id="team-a",
    tool_name="tool_x",
    plugin_id="OUTPUT_LENGTH_GUARD",
    mode="enforce",
    priority=50,
    config=None,
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
    b.config = config if config is not None else {"max_chars": 2000, "strategy": "truncate"}
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
                        plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                        mode=PluginBindingMode.ENFORCE,
                        priority=50,
                        config={"min_chars": 0, "max_chars": 2000, "strategy": "truncate", "ellipsis": "..."},
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
        assert r.plugin_id == "OUTPUT_LENGTH_GUARD"
        assert r.mode == "enforce"
        assert r.priority == 50
        assert r.config == {"min_chars": 0, "max_chars": 2000, "strategy": "truncate", "ellipsis": "..."}
        assert r.created_by == "admin@example.com"
        assert r.updated_by == "admin@example.com"

        # Verify the row was actually persisted in the DB
        row = db_session.query(ToolPluginBinding).one()
        assert row.tool_name == "tool_x"
        assert row.team_id == "team-a"

    def test_update_existing_binding(self, service, db_session):
        """Re-upserting the same triple updates mutable fields; id and created_by are preserved."""
        request_v1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_x"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=10,
                            config={"min_chars": 0, "max_chars": 500, "strategy": "truncate", "ellipsis": "..."},
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
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.ENFORCE,
                            priority=50,
                            config={"min_chars": 0, "max_chars": 2000, "strategy": "block", "ellipsis": "..."},
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
        assert r.config == {"min_chars": 0, "max_chars": 2000, "strategy": "block", "ellipsis": "..."}
        assert r.updated_by == "updater@example.com"
        assert r.created_by == "creator@example.com"     # creation author unchanged

    def test_config_is_fully_replaced_not_merged(self, service, db_session):
        """On update, config is entirely replaced — values absent from the new payload do not survive."""
        r1 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id=PluginId.RATE_LIMITER, config={"by_user": "10/s", "by_tenant": None, "by_tool": None})]
                )
            }
        )
        service.upsert_bindings(db_session, r1, caller_email="admin@example.com")

        # Upsert with by_tenant set and by_user explicitly None — original by_user value must NOT survive
        r2 = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id=PluginId.RATE_LIMITER, config={"by_user": None, "by_tenant": "600/m", "by_tool": None})]
                )
            }
        )
        results = service.upsert_bindings(db_session, r2, caller_email="admin@example.com")

        assert results[0].config == {"by_user": None, "by_tenant": "600/m", "by_tool": None}
        assert results[0].config["by_user"] is None  # original "10/s" is gone

    def test_multiple_tool_names_in_one_policy(self, service, db_session):
        """A policy with multiple tool_names produces one binding per tool, each with the full config."""
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["tool_a", "tool_b"],
                            plugin_id=PluginId.RATE_LIMITER,
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=20,
                            config={"by_user": "60/m", "by_tenant": "600/m", "by_tool": None},
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
        assert tool_a.plugin_id == "RATE_LIMITER"
        assert tool_a.mode == "permissive"
        assert tool_a.priority == 20
        assert tool_a.config == {"by_user": "60/m", "by_tenant": "600/m", "by_tool": None}

        tool_b = by_tool["tool_b"]
        assert tool_b.team_id == "team-a"
        assert tool_b.plugin_id == "RATE_LIMITER"
        assert tool_b.mode == "permissive"
        assert tool_b.priority == 20
        assert tool_b.config == {"by_user": "60/m", "by_tenant": "600/m", "by_tool": None}

    def test_multiple_teams(self, service, db_session):
        """A request spanning two teams produces one binding per team."""
        request = ToolPluginBindingRequest(
            teams={
                "team-a": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id=PluginId.OUTPUT_LENGTH_GUARD, config={"min_chars": 0, "max_chars": 500, "strategy": "block", "ellipsis": "..."})]
                ),
                "team-b": TeamPolicies(
                    policies=[PluginPolicyItem(tool_names=["tool_y"], plugin_id=PluginId.SECRETS_DETECTION, config={"enabled": {}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": False, "min_findings_to_block": 1})]
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
        assert team_a.plugin_id == "OUTPUT_LENGTH_GUARD"
        assert team_a.config == {"min_chars": 0, "max_chars": 500, "strategy": "block", "ellipsis": "..."}

        team_b = by_team["team-b"]
        assert team_b.tool_name == "tool_y"
        assert team_b.plugin_id == "SECRETS_DETECTION"
        assert team_b.config == {"enabled": {}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": False, "min_findings_to_block": 1}

    def test_caller_email_stored_in_audit_fields(self, service, db_session, simple_request):
        """caller_email is written to both created_by and updated_by on insert."""
        results = service.upsert_bindings(db_session, simple_request, caller_email="admin@example.com")

        assert results[0].created_by == "admin@example.com"
        assert results[0].updated_by == "admin@example.com"


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
                "team-a": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id=PluginId.RATE_LIMITER, config={"by_user": None, "by_tenant": None, "by_tool": None})]),
                "team-b": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_y"], plugin_id=PluginId.SECRETS_DETECTION, config={"enabled": {}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": False, "min_findings_to_block": 1})]),
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
                    policies=[PluginPolicyItem(tool_names=["tool_z"], plugin_id=PluginId.OUTPUT_LENGTH_GUARD, priority=10, config={"min_chars": 0, "max_chars": 500, "strategy": "block", "ellipsis": "..."})]
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
            teams={"team-a": TeamPolicies(policies=[PluginPolicyItem(tool_names=["tool_x"], plugin_id=PluginId.RATE_LIMITER, config={"by_user": None, "by_tenant": None, "by_tool": None})])}
        )
        inserted = service.upsert_bindings(db_session, r, caller_email="admin@example.com")
        binding_id = inserted[0].id

        deleted = service.delete_binding(db_session, binding_id)

        assert deleted.id == binding_id
        assert deleted.team_id == "team-a"
        assert deleted.tool_name == "tool_x"
        assert deleted.plugin_id == "RATE_LIMITER"
        assert deleted.config == {"by_user": None, "by_tenant": None, "by_tool": None}
        # Confirm the row is gone from the DB
        assert db_session.query(ToolPluginBinding).filter_by(id=binding_id).first() is None

    def test_delete_not_found(self, service, db_session):
        """delete_binding raises ToolPluginBindingNotFoundError for an unknown ID."""
        with pytest.raises(ToolPluginBindingNotFoundError, match="not found"):
            service.delete_binding(db_session, "nonexistent-id")


# ---------------------------------------------------------------------------
# Schema validation tests — OutputLengthGuardConfig
# ---------------------------------------------------------------------------


class TestOutputLengthGuardConfig:
    """Pydantic validation for OutputLengthGuardConfig."""

    def test_valid_defaults(self):
        """Default construction succeeds — schema defaults remain available for internal/plugin-manager use."""
        cfg = OutputLengthGuardConfig()
        assert cfg.min_chars == 0
        assert cfg.max_chars == 2000
        assert cfg.strategy == "truncate"
        assert cfg.ellipsis == "..."

    def test_valid_explicit(self):
        """Explicit valid values are accepted."""
        cfg = OutputLengthGuardConfig(min_chars=100, max_chars=500, strategy="block", ellipsis="[cut]")
        assert cfg.min_chars == 100
        assert cfg.max_chars == 500
        assert cfg.strategy == "block"
        assert cfg.ellipsis == "[cut]"

    def test_min_equal_to_max_rejected(self):
        """min_chars == max_chars is rejected by the cross-validator."""
        with pytest.raises(ValidationError, match="min_chars must be less than max_chars"):
            OutputLengthGuardConfig(min_chars=500, max_chars=500, strategy="truncate", ellipsis="...")

    def test_min_greater_than_max_rejected(self):
        """min_chars > max_chars is rejected by the cross-validator."""
        with pytest.raises(ValidationError, match="min_chars must be less than max_chars"):
            OutputLengthGuardConfig(min_chars=1000, max_chars=100, strategy="truncate", ellipsis="...")

    def test_max_chars_must_be_greater_than_one(self):
        """max_chars=1 is rejected (must be > 1)."""
        with pytest.raises(ValidationError, match=r"(?s)max_chars.*greater than 1"):
            OutputLengthGuardConfig(min_chars=0, max_chars=1, strategy="truncate", ellipsis="...")

    def test_min_chars_must_be_non_negative(self):
        """min_chars=-1 is rejected (must be >= 0)."""
        with pytest.raises(ValidationError, match=r"(?s)min_chars.*greater than or equal to 0"):
            OutputLengthGuardConfig(min_chars=-1, max_chars=100, strategy="truncate", ellipsis="...")

    def test_invalid_strategy(self):
        """Strategy values other than 'truncate' or 'block' are rejected."""
        with pytest.raises(ValidationError, match=r"(?s)strategy.*'truncate' or 'block'"):
            OutputLengthGuardConfig(min_chars=0, max_chars=2000, strategy="drop", ellipsis="...")

    def test_ellipsis_too_long(self):
        """ellipsis longer than 20 characters is rejected."""
        with pytest.raises(ValidationError, match=r"(?s)ellipsis.*at most 20 characters"):
            OutputLengthGuardConfig(min_chars=0, max_chars=2000, strategy="truncate", ellipsis="x" * 21)

    def test_extra_fields_forbidden(self):
        """Unknown fields are rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            OutputLengthGuardConfig(min_chars=0, max_chars=2000, strategy="truncate", ellipsis="...", unknown_field="bad")


# ---------------------------------------------------------------------------
# Schema validation tests — RateLimiterConfig
# ---------------------------------------------------------------------------


class TestRateLimiterConfig:
    """Pydantic validation for RateLimiterConfig."""

    def test_all_none_is_valid(self):
        """All-None construction is valid (no limits configured)."""
        cfg = RateLimiterConfig()
        assert cfg.by_user is None
        assert cfg.by_tenant is None
        assert cfg.by_tool is None

    def test_valid_per_minute(self):
        """Rate strings ending in /m are accepted."""
        cfg = RateLimiterConfig(by_user="60/m", by_tenant="600/m", by_tool="10/m")
        assert cfg.by_user == "60/m"
        assert cfg.by_tenant == "600/m"

    def test_valid_per_second(self):
        """Rate strings ending in /s are accepted."""
        cfg = RateLimiterConfig(by_user="10/s")
        assert cfg.by_user == "10/s"

    def test_invalid_period_h(self):
        """Period /h is not accepted."""
        with pytest.raises(ValidationError, match=r"Rate string '60/h' is invalid"):
            RateLimiterConfig(by_user="60/h")

    def test_invalid_no_slash(self):
        """Rate strings without a slash are rejected."""
        with pytest.raises(ValidationError, match=r"Rate string '100' is invalid"):
            RateLimiterConfig(by_tool="100")

    def test_invalid_missing_count(self):
        """Rate strings missing the numeric count are rejected."""
        with pytest.raises(ValidationError, match=r"Rate string '/m' is invalid"):
            RateLimiterConfig(by_tenant="/m")

    def test_invalid_non_numeric_count(self):
        """Non-numeric count is rejected."""
        with pytest.raises(ValidationError, match=r"Rate string 'fast/m' is invalid"):
            RateLimiterConfig(by_user="fast/m")

    def test_extra_fields_forbidden(self):
        """Unknown fields are rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            RateLimiterConfig(by_ip="10/m")


# ---------------------------------------------------------------------------
# Schema validation tests — SecretsDetectionConfig
# ---------------------------------------------------------------------------


class TestSecretsDetectionConfig:
    """Pydantic validation for SecretsDetectionConfig."""

    def test_valid_defaults(self):
        """Default construction succeeds — schema defaults remain available for internal/plugin-manager use."""
        cfg = SecretsDetectionConfig()
        assert cfg.redact is True
        assert cfg.redaction_text == "[REDACTED]"
        assert cfg.block_on_detection is False
        assert cfg.min_findings_to_block == 1
        assert cfg.enabled == {}

    def test_valid_explicit(self):
        """Explicit valid values are accepted."""
        cfg = SecretsDetectionConfig(
            enabled={"aws_key": True, "github_token": False},
            redact=True,
            redaction_text="***",
            block_on_detection=True,
            min_findings_to_block=3,
        )
        assert cfg.enabled == {"aws_key": True, "github_token": False}
        assert cfg.min_findings_to_block == 3

    def test_min_findings_must_be_at_least_one(self):
        """min_findings_to_block=0 is rejected (must be >= 1)."""
        with pytest.raises(ValidationError, match=r"(?s)min_findings_to_block.*greater than or equal to 1"):
            SecretsDetectionConfig(enabled={}, redact=True, redaction_text="[REDACTED]", block_on_detection=False, min_findings_to_block=0)

    def test_redaction_text_too_long(self):
        """redaction_text longer than 50 characters is rejected."""
        with pytest.raises(ValidationError, match=r"(?s)redaction_text.*at most 50 characters"):
            SecretsDetectionConfig(enabled={}, redact=True, redaction_text="x" * 51, block_on_detection=False, min_findings_to_block=1)

    def test_extra_fields_forbidden(self):
        """Unknown fields are rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            SecretsDetectionConfig(enabled={}, redact=True, redaction_text="[REDACTED]", block_on_detection=False, min_findings_to_block=1, scan_mode="deep")


# ---------------------------------------------------------------------------
# Schema validation tests — PluginPolicyItem cross-validation
# ---------------------------------------------------------------------------


class TestPluginPolicyItemValidation:
    """Tests for PluginPolicyItem including config cross-validation per plugin."""

    def test_defaults_mode_and_priority(self):
        """PluginPolicyItem defaults for mode and priority; RATE_LIMITER accepts all-null config (explicit no-limit)."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id=PluginId.RATE_LIMITER,
            config={"by_user": None, "by_tenant": None, "by_tool": None},
        )
        assert item.mode == PluginBindingMode.ENFORCE
        assert item.priority == 50

    def test_output_length_guard_valid_config(self):
        """OUTPUT_LENGTH_GUARD with all required fields passes cross-validation."""
        item = PluginPolicyItem(
            tool_names=["tool_x"],
            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
            config={"min_chars": 0, "max_chars": 500, "strategy": "block", "ellipsis": "..."},
        )
        assert item.plugin_id == PluginId.OUTPUT_LENGTH_GUARD

    def test_output_length_guard_invalid_config_rejected(self):
        """OUTPUT_LENGTH_GUARD with min >= max is caught by PluginPolicyItem validator."""
        with pytest.raises(ValidationError, match="min_chars must be less than max_chars"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                config={"min_chars": 5000, "max_chars": 3000, "strategy": "truncate", "ellipsis": "..."},
            )

    def test_output_length_guard_rejects_empty_config(self):
        """OUTPUT_LENGTH_GUARD with {} is rejected — all four fields are required."""
        with pytest.raises(ValidationError, match="Missing config fields for OUTPUT_LENGTH_GUARD"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                config={},
            )

    def test_rate_limiter_valid_config(self):
        """RATE_LIMITER with all three fields (some None) passes cross-validation."""
        item = PluginPolicyItem(
            tool_names=["tool_y"],
            plugin_id=PluginId.RATE_LIMITER,
            config={"by_user": "60/m", "by_tenant": "600/m", "by_tool": None},
        )
        assert item.plugin_id == PluginId.RATE_LIMITER

    def test_rate_limiter_invalid_config_rejected(self):
        """RATE_LIMITER with invalid rate string format is caught by PluginPolicyItem validator."""
        with pytest.raises(ValidationError, match=r"Rate string '60/h' is invalid"):
            PluginPolicyItem(
                tool_names=["tool_y"],
                plugin_id=PluginId.RATE_LIMITER,
                config={"by_user": "60/h", "by_tenant": None, "by_tool": None},  # /h not allowed
            )

    def test_secrets_detection_valid_config(self):
        """SECRETS_DETECTION with all required fields passes cross-validation."""
        item = PluginPolicyItem(
            tool_names=["tool_z"],
            plugin_id=PluginId.SECRETS_DETECTION,
            config={"enabled": {"aws_key": True}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": True, "min_findings_to_block": 2},
        )
        assert item.plugin_id == PluginId.SECRETS_DETECTION

    def test_secrets_detection_invalid_config_rejected(self):
        """SECRETS_DETECTION with min_findings_to_block=0 is caught by PluginPolicyItem validator."""
        with pytest.raises(ValidationError, match=r"(?s)min_findings_to_block.*greater than or equal to 1"):
            PluginPolicyItem(
                tool_names=["tool_z"],
                plugin_id=PluginId.SECRETS_DETECTION,
                config={"enabled": {}, "redact": True, "redaction_text": "[REDACTED]", "block_on_detection": False, "min_findings_to_block": 0},
            )

    def test_secrets_detection_rejects_empty_config(self):
        """SECRETS_DETECTION with {} is rejected — all five fields are required."""
        with pytest.raises(ValidationError, match="Missing config fields for SECRETS_DETECTION"):
            PluginPolicyItem(
                tool_names=["tool_z"],
                plugin_id=PluginId.SECRETS_DETECTION,
                config={},
            )

    def test_empty_tool_names_rejected(self):
        """tool_names=[] is rejected (min_length=1)."""
        with pytest.raises(ValidationError, match=r"(?s)tool_names.*at least 1 item"):
            PluginPolicyItem(
                tool_names=[],
                plugin_id=PluginId.RATE_LIMITER,
                config={"by_user": None, "by_tenant": None, "by_tool": None},
            )

    def test_priority_below_minimum_rejected(self):
        """priority=0 is rejected (ge=1)."""
        with pytest.raises(ValidationError, match=r"(?s)priority.*greater than or equal to 1"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.RATE_LIMITER,
                priority=0,
                config={"by_user": None, "by_tenant": None, "by_tool": None},
            )

    def test_priority_above_maximum_rejected(self):
        """priority=1001 is rejected (le=1000)."""
        with pytest.raises(ValidationError, match=r"(?s)priority.*less than or equal to 1000"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.RATE_LIMITER,
                priority=1001,
                config={"by_user": None, "by_tenant": None, "by_tool": None},
            )

    def test_invalid_plugin_id_rejected(self):
        """An unrecognised plugin_id string is rejected by the PluginId enum."""
        with pytest.raises(ValidationError, match=r"(?s)plugin_id.*Input should be"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id="UNKNOWN_PLUGIN",  # type: ignore[arg-type]
                config={},
            )

    def test_extra_fields_forbidden(self):
        """Unknown fields on PluginPolicyItem are rejected (extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.RATE_LIMITER,
                config={"by_user": None, "by_tenant": None, "by_tool": None},
                unknown_key="bad",
            )

    def test_config_field_is_required(self):
        """config is a required field — omitting it is rejected at schema validation time."""
        with pytest.raises(ValidationError, match=r"(?s)config.*Field required"):
            PluginPolicyItem(
                tool_names=["tool_x"],
                plugin_id=PluginId.RATE_LIMITER,
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

    def test_plugin_id_enum_values(self):
        """PluginId enum covers all expected plugin identifiers."""
        assert PluginId.OUTPUT_LENGTH_GUARD == "OUTPUT_LENGTH_GUARD"
        assert PluginId.RATE_LIMITER == "RATE_LIMITER"
        assert PluginId.SECRETS_DETECTION == "SECRETS_DETECTION"

    def test_plugin_binding_mode_enum_values(self):
        """PluginBindingMode enum covers all expected execution modes."""
        assert PluginBindingMode.ENFORCE == "enforce"
        assert PluginBindingMode.PERMISSIVE == "permissive"
        assert PluginBindingMode.DISABLED == "disabled"

    def test_all_plugin_errors_collected_across_list(self):
        """When multiple PluginPolicyItems are invalid, all their errors appear in one ValidationError.

        Previously, a ValidationError escaping from the model_validator would short-circuit
        list validation and hide errors from subsequent items. After the fix, each item's
        errors are wrapped as ValueError so Pydantic can collect every item.

        NOTE: items must be passed as raw dicts so that Pydantic constructs each
        PluginPolicyItem internally — if you pre-construct them with PluginPolicyItem(...),
        Python evaluates each call before TeamPolicies() is reached, raising immediately.
        """
        with pytest.raises(ValidationError) as exc_info:
            ToolPluginBindingRequest.model_validate(
                {
                    "teams": {
                        "team-a": {
                            "policies": [
                                # item 0: OLG with an invalid value — triggers the new ValueError format
                                {"tool_names": ["tool_x"], "plugin_id": "OUTPUT_LENGTH_GUARD", "config": {"min_chars": 0, "max_chars": 2000, "strategy": "drop", "ellipsis": "..."}},
                                # item 1: RATE_LIMITER with missing fields — triggers the existing ValueError
                                {"tool_names": ["tool_y"], "plugin_id": "RATE_LIMITER", "config": {}},
                            ]
                        }
                    }
                }
            )
        errors = exc_info.value.errors()
        assert len(errors) == 2, f"Expected 2 errors, got {len(errors)}: {errors}"

        # Sort by the integer index in the loc tuple so assertions are deterministic regardless of collection order
        errors_by_index = sorted(errors, key=lambda e: next(x for x in e["loc"] if isinstance(x, int)))

        # item 0: OLG — strategy field rejected
        assert errors_by_index[0]["loc"] == ("teams", "team-a", "policies", 0)
        assert errors_by_index[0]["msg"] == "Value error, Invalid OUTPUT_LENGTH_GUARD config: [strategy: Input should be 'truncate' or 'block']"

        # item 1: RATE_LIMITER — missing all three fields (sorted alphabetically in the error)
        assert errors_by_index[1]["loc"] == ("teams", "team-a", "policies", 1)
        assert errors_by_index[1]["msg"] == "Value error, Missing config fields for RATE_LIMITER: ['by_tenant', 'by_tool', 'by_user']"


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
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.ENFORCE,
                            priority=50,
                            config={"min_chars": 0, "max_chars": 2000, "strategy": "truncate", "ellipsis": "..."},
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
                            plugin_id=PluginId.RATE_LIMITER,
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=10,
                            config={"by_user": "100/m", "by_tenant": "1000/m", "by_tool": None},
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
        assert plugin_ids == {"OUTPUT_LENGTH_GUARD", "RATE_LIMITER"}

    def test_returns_only_wildcard_for_unknown_tool(self):
        """A tool with no exact binding still gets the wildcard binding."""
        results = get_bindings_for_tool(self._db, "team-a", "other_tool")
        assert len(results) == 1
        assert results[0].plugin_id == "RATE_LIMITER"

    def test_returns_empty_for_unknown_team(self):
        """An unknown team has no bindings."""
        results = get_bindings_for_tool(self._db, "unknown-team", "tool_x")
        assert results == []

    def test_exact_overrides_wildcard_for_same_plugin(self, service, db_session):
        """When both an exact and a wildcard binding exist for the same plugin_id,
        the more recently updated one wins (exact was inserted after wildcard here)."""
        # Insert a wildcard OUTPUT_LENGTH_GUARD first
        wc_req = ToolPluginBindingRequest(
            teams={
                "team-b": TeamPolicies(
                    policies=[
                        PluginPolicyItem(
                            tool_names=["*"],
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.PERMISSIVE,
                            priority=1,
                            config={"min_chars": 0, "max_chars": 100, "strategy": "truncate", "ellipsis": "..."},
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
                            plugin_id=PluginId.OUTPUT_LENGTH_GUARD,
                            mode=PluginBindingMode.ENFORCE,
                            priority=99,
                            config={"min_chars": 0, "max_chars": 9999, "strategy": "truncate", "ellipsis": "..."},
                        )
                    ]
                )
            }
        )
        service.upsert_bindings(db_session, exact_req, caller_email="admin@example.com")

        results = get_bindings_for_tool(db_session, "team-b", "tool_z")
        # Only one entry per plugin_id — the one with the higher updated_at wins
        olg_results = [b for b in results if b.plugin_id == "OUTPUT_LENGTH_GUARD"]
        assert len(olg_results) == 1
        # The exact binding has priority=99 (inserted last → higher updated_at)
        assert olg_results[0].priority == 99

    def test_does_not_cross_team_boundaries(self):
        """Bindings for a different team are not returned."""
        results = get_bindings_for_tool(self._db, "team-b", "tool_x")
        assert results == []
