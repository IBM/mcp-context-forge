# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool validation policy resolver.
"""

# Standard
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, EmailTeam, EmailUser, Role, UserRole
from mcpgateway.services import tool_validation_policy as policy_module
from mcpgateway.services.permission_service import PermissionService
from mcpgateway.services.tool_validation_policy import (
    admit_stored_tool,
    admit_tool,
    apply_refusal,
    check_policy_permission,
    evaluate_tool_policy,
    global_policy_expression,
    policy_changed,
    record_policy_change,
    resolve_policy,
    SOURCE_GATEWAY,
    SOURCE_GLOBAL,
    SOURCE_NONE,
    SOURCE_TOOL,
)
from mcpgateway.utils.cel_runner import CelBusy, CelError, CelEvaluationError, CelSyntaxError, CelTimeout

DEFAULT_PATTERNS = ["&&", "||", "$("]
GATEWAY_REASON = "denied by the gateway-level validation policy"


@pytest.fixture(autouse=True)
def strict_defaults(monkeypatch):
    """Run in-process, strict, with the shipped global pattern list."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", list(DEFAULT_PATTERNS))


# --- global expression -------------------------------------------------------


def test_global_expression_from_default_patterns():
    """The shipped pattern list compiles to one negated contains-chain."""
    assert global_policy_expression() == '!(description.contains("&&") || description.contains("||") || description.contains("$("))'


def test_global_expression_skips_blank_patterns(monkeypatch):
    """Empty and whitespace-only entries are ignored, as the old loop ignored them."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["", "  ", "&&"])
    assert global_policy_expression() == '!(description.contains("&&"))'


def test_global_expression_none_when_disabled_or_empty(monkeypatch):
    """No global policy when the flag is off or nothing is listed."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", [])
    assert global_policy_expression() is None
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["&&"])
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert global_policy_expression() is None


def test_global_expression_quotes_special_characters(monkeypatch):
    """A pattern containing quotes or backslashes still matches literally."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ['say "hi"', "a\\b"])
    assert evaluate_tool_policy(description='please say "hi"', tool_name="t").allowed is False
    assert evaluate_tool_policy(description="path a\\b here", tool_name="t").allowed is False
    assert evaluate_tool_policy(description="harmless", tool_name="t").allowed is True


# --- resolution order --------------------------------------------------------


def test_tool_policy_wins_over_gateway_and_global():
    """The most specific level decides."""
    assert resolve_policy("true", "false") == ("true", SOURCE_TOOL)


def test_blank_tool_policy_inherits_gateway():
    """Whitespace counts as empty."""
    assert resolve_policy("   ", " false ") == ("false", SOURCE_GATEWAY)


def test_empty_levels_fall_through_to_global():
    """With nothing stored, the global settings apply."""
    expression, source = resolve_policy(None, None)
    assert source == SOURCE_GLOBAL
    assert expression == global_policy_expression()


def test_non_text_values_are_treated_as_empty():
    """A column read through a mock or a wrong type never becomes a policy."""
    assert resolve_policy(MagicMock(), 42) == (global_policy_expression(), SOURCE_GLOBAL)


def test_non_text_description_and_name_count_as_empty():
    """Only text reaches the sandbox; anything else evaluates as an empty string."""
    decision = evaluate_tool_policy(description=MagicMock(), tool_name=42, gateway_policy='description == "" && tool_name == ""')
    assert decision.allowed is True


def test_no_policy_anywhere(monkeypatch):
    """Global disabled and no overrides means every tool is allowed."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert resolve_policy(None, None) == (None, SOURCE_NONE)
    decision = evaluate_tool_policy(description="rm -rf / && echo", tool_name="t")
    assert decision.allowed is True
    assert decision.source == SOURCE_NONE


def test_gateway_override_applies_even_when_global_disabled(monkeypatch):
    """The enabled flag governs the global default only."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert evaluate_tool_policy(description="x", tool_name="t", gateway_policy="false").allowed is False


@pytest.mark.parametrize(("old", "new", "changed"), [(None, "", False), ("true", " true ", False), (None, "true", True), ("true", None, True), ("true", "false", True)])
def test_policy_changed_compares_normalised_text(old, new, changed):
    """A form that resubmits the stored policy is not a change; a real edit is."""
    assert policy_changed(old, new) is changed


# --- evaluation -------------------------------------------------------------


@pytest.mark.parametrize("pattern", DEFAULT_PATTERNS)
@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_default_patterns_are_denied_wherever_they_appear(pattern, position):
    """Each shipped pattern is refused at the start, middle, or end of a description."""
    description = {"start": f"{pattern} tail", "middle": f"head {pattern} tail", "end": f"head {pattern}"}[position]
    decision = evaluate_tool_policy(description=description, tool_name="t")
    assert decision.allowed is False
    assert decision.source == SOURCE_GLOBAL
    assert decision.reason == "denied by the global validation policy"


@pytest.mark.parametrize("description", ["A safe description", "", None, "Markdown: `code`; cmd | grep x; > quote"])
def test_descriptions_without_patterns_are_allowed(description):
    """Safe text, empty text, no text, and the Markdown the old loop allowed all pass."""
    assert evaluate_tool_policy(description=description, tool_name="t").allowed is True


def test_gateway_override_relaxes_the_global_rule():
    """A gateway policy replaces the global one entirely for its tools."""
    decision = evaluate_tool_policy(description="make && make test", tool_name="build", gateway_policy='!description.contains("$(")')
    assert decision.allowed is True
    assert decision.source == SOURCE_GATEWAY


def test_reason_names_each_level_without_repeating_the_word_tool():
    """The refusal text reads naturally at every level."""
    assert evaluate_tool_policy(description="x", tool_name="t", tool_policy="false").reason == "denied by the tool-level validation policy"
    assert evaluate_tool_policy(description="x", tool_name="t", gateway_policy="false").reason == GATEWAY_REASON
    assert evaluate_tool_policy(description="a && b", tool_name="t").reason == "denied by the global validation policy"


def test_tool_override_can_branch_on_name():
    """A per-tool policy sees the tool name."""
    policy = 'tool_name == "run_query"'
    assert evaluate_tool_policy(description="x", tool_name="run_query", tool_policy=policy).allowed is True
    assert evaluate_tool_policy(description="x", tool_name="other", tool_policy=policy).allowed is False


@pytest.mark.parametrize("error", [CelSyntaxError("unexpected token"), CelEvaluationError("unknown variable(s) ['foo']")])
def test_broken_expression_is_refused_without_a_retry(monkeypatch, error):
    """A policy that cannot run because of its own text is refused at once."""
    sandbox = Mock(side_effect=error)
    monkeypatch.setattr(policy_module, "evaluate_expression", sandbox)
    decision = evaluate_tool_policy(description="x", tool_name="t", gateway_policy="true")
    assert decision.allowed is False
    assert decision.reason == "could not be evaluated against the gateway-level validation policy"
    assert sandbox.call_count == 1


@pytest.mark.parametrize("error", [CelBusy("CEL sandbox has no free worker"), CelTimeout("CEL expression exceeded the execution time limit"), CelError("worker died")])
def test_sandbox_failure_is_retried_once_then_refused(monkeypatch, error, caplog):
    """A busy, slow, or dead sandbox gets one retry; a second failure refuses the tool and logs the cause."""
    sandbox = Mock(side_effect=error)
    monkeypatch.setattr(policy_module, "evaluate_expression", sandbox)
    with caplog.at_level(logging.WARNING, logger=policy_module.__name__):
        decision = evaluate_tool_policy(description="x", tool_name="t", tool_policy="true")
    assert f"could not be evaluated for tool 't': {error}" in caplog.text
    assert decision.allowed is False
    assert decision.reason == "could not be evaluated against the tool-level validation policy"
    assert sandbox.call_count == 2


def test_sandbox_failure_that_clears_on_retry_decides_normally(monkeypatch):
    """One hiccup followed by a result is just a result."""
    monkeypatch.setattr(policy_module, "evaluate_expression", Mock(side_effect=[CelBusy("busy"), True]))
    assert evaluate_tool_policy(description="x", tool_name="t", gateway_policy="true").allowed is True


# --- admit_tool and the strict flag -----------------------------------------


def test_admit_returns_none_when_allowed(caplog):
    """An allowed tool produces no refusal and a debug line naming the level."""
    with caplog.at_level(logging.DEBUG, logger=policy_module.__name__):
        assert admit_tool(description="safe", tool_name="t", context="unit") is None
    assert "Tool validation policy (global) allowed tool 't' during unit" in caplog.text


def test_admit_refuses_in_strict_mode(caplog):
    """Strict mode returns the bare reason and logs which level decided."""
    with caplog.at_level(logging.INFO, logger=policy_module.__name__):
        refusal = admit_tool(description="a && b", tool_name="build", gateway_policy=None, context="unit")
    assert refusal == "denied by the global validation policy"
    assert "Tool validation policy (global) refused tool 'build' during unit" in caplog.text


def test_admit_warns_and_allows_when_not_strict(monkeypatch, caplog):
    """With VALIDATION_STRICT off a refused tool is logged once and stored."""
    monkeypatch.setattr(settings, "validation_strict", False)
    with caplog.at_level(logging.WARNING, logger=policy_module.__name__):
        assert admit_tool(description="a && b || c $(d)", tool_name="build", context="unit") is None
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Tool 'build' denied by the global validation policy (VALIDATION_STRICT=false, proceeding) during unit"


def test_admit_refuses_when_the_sandbox_stays_down(monkeypatch):
    """A check that could not run refuses the tool, naming the level but not the technical cause."""
    monkeypatch.setattr(policy_module, "evaluate_expression", Mock(side_effect=CelBusy("CEL sandbox has no free worker")))
    assert admit_tool(description="x", tool_name="t", gateway_policy="true", context="unit") == "could not be evaluated against the gateway-level validation policy"


def test_admit_stored_tool_checks_the_upstream_text_behind_a_customised_description():
    """A stored tool is judged on the upstream text too, so the result matches what the next refresh would do."""
    tool = SimpleNamespace(original_name="build", description="clean custom text", original_description="upstream && dirty", tool_validation_policy=None)
    assert admit_stored_tool(tool, None, "unit") == "denied by the global validation policy"
    tool.original_description = "clean custom text"
    assert admit_stored_tool(tool, None, "unit") is None


# --- applying to rows ------------------------------------------------------------


def test_refusal_disables_the_row_and_records_why():
    """A refused tool is switched off with the reason stored beside it."""
    tool = SimpleNamespace(enabled=True, validation_refusal=None)
    apply_refusal(tool, GATEWAY_REASON)
    assert (tool.enabled, tool.validation_refusal) == (False, GATEWAY_REASON)


def test_clearing_a_refusal_re_enables_the_row():
    """A tool the policy refused earlier and now allows comes back on."""
    tool = SimpleNamespace(enabled=False, validation_refusal=GATEWAY_REASON)
    apply_refusal(tool, None)
    assert (tool.enabled, tool.validation_refusal) == (True, None)


def test_operator_disabled_tool_is_left_alone():
    """A tool switched off by hand, never refused, is not touched by an allow decision."""
    tool = SimpleNamespace(enabled=False, validation_refusal=None)
    apply_refusal(tool, None)
    assert (tool.enabled, tool.validation_refusal) == (False, None)


# --- permission and audit -------------------------------------------------------


@pytest.fixture
def permission_service(monkeypatch):
    """Replace the permission service with one whose answer the test controls."""
    instance = SimpleNamespace(check_permission=AsyncMock(return_value=False))
    monkeypatch.setattr("mcpgateway.services.permission_service.PermissionService", Mock(return_value=instance))
    return instance


def _db(is_personal):
    """A session whose only query answers whether the record's team is personal."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = is_personal
    return db


@pytest.mark.asyncio
async def test_check_policy_permission_refuses_without_the_permission(permission_service):
    """A caller without validation_policy.manage cannot set a policy on a shared team's record."""
    with pytest.raises(PermissionError, match="requires the validation_policy.manage permission"):
        await check_policy_permission(_db(False), "dev@example.com", resource_type="tools", team_id="team-1")
    permission_service.check_permission.assert_awaited_once_with("dev@example.com", "validation_policy.manage", resource_type="tools", team_id="team-1")


@pytest.mark.asyncio
async def test_check_policy_permission_refuses_an_unknown_caller(permission_service):
    """No actor means no permission check and no policy."""
    with pytest.raises(PermissionError):
        await check_policy_permission(_db(False), None, resource_type="gateways", team_id=None)
    permission_service.check_permission.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_policy_permission_accepts_the_permission(permission_service):
    """A caller holding the permission passes."""
    permission_service.check_permission.return_value = True
    await check_policy_permission(_db(False), "admin@example.com", resource_type="gateways", team_id="team-1")
    permission_service.check_permission.assert_awaited_once_with("admin@example.com", "validation_policy.manage", resource_type="gateways", team_id="team-1")


@pytest.mark.parametrize(("team_id", "is_personal"), [("personal-1", True), ("missing", None), (None, False)])
@pytest.mark.asyncio
async def test_check_policy_permission_ignores_personal_team_roles(permission_service, team_id, is_personal):
    """A personal team, an unknown team, or no team is checked against global roles only."""
    permission_service.check_permission.return_value = True
    await check_policy_permission(_db(is_personal), "dev@example.com", resource_type="gateways", team_id=team_id)
    permission_service.check_permission.assert_awaited_once_with("dev@example.com", "validation_policy.manage", resource_type="gateways", team_id=None)


@pytest.fixture
def rbac_db():
    """An in-memory database with a user who is team admin of a personal team and of a shared team."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    password = "$argon2id$v=19$m=65536,t=3,p=1$test"  # pragma: allowlist secret
    db.add(EmailUser(email="admin@test.local", password_hash=password, full_name="Admin", is_admin=True, is_active=True))
    db.add(EmailUser(email="dev@test.local", password_hash=password, full_name="Dev", is_admin=False, is_active=True))
    db.flush()
    role = Role(
        id=str(uuid.uuid4()),
        name="team_admin",
        description="Team administrator",
        scope="team",
        permissions=["validation_policy.manage"],
        created_by="admin@test.local",
        is_system_role=True,
        is_active=True,
    )
    db.add(role)
    personal = EmailTeam(id=str(uuid.uuid4()), name="dev personal", slug="dev-personal", created_by="dev@test.local", is_personal=True)
    shared = EmailTeam(id=str(uuid.uuid4()), name="Shared Team", slug="shared-team", created_by="admin@test.local", is_personal=False)
    db.add_all([personal, shared])
    db.flush()
    for team in (personal, shared):
        db.add(UserRole(user_email="dev@test.local", role_id=role.id, scope="team", scope_id=team.id, granted_by="admin@test.local", is_active=True))
    db.commit()
    yield db, personal.id, shared.id
    db.close()


@pytest.mark.asyncio
async def test_personal_team_admin_cannot_set_a_policy(rbac_db):
    """The team_admin role every user holds on their personal team never grants the policy permission."""
    db, personal_id, shared_id = rbac_db
    PermissionService(db).clear_cache()
    with pytest.raises(PermissionError, match="validation_policy.manage"):
        await check_policy_permission(db, "dev@test.local", resource_type="gateways", team_id=personal_id)
    with pytest.raises(PermissionError, match="validation_policy.manage"):
        await check_policy_permission(db, "dev@test.local", resource_type="gateways", team_id=None)
    await check_policy_permission(db, "dev@test.local", resource_type="gateways", team_id=shared_id)
    await check_policy_permission(db, "admin@test.local", resource_type="gateways", team_id=personal_id)


def test_record_policy_change_writes_old_and_new_expressions(monkeypatch):
    """The audit entry names the actor, the record, and both expressions in full."""
    audit = Mock()
    monkeypatch.setattr(policy_module, "get_audit_trail_service", Mock(return_value=audit))
    record_policy_change(resource_type="gateway", resource_id="gw-1", resource_name="gw", team_id="team-1", user_email="admin@example.com", old=None, new=" true ")
    audit.log_action.assert_called_once_with(
        user_id="admin@example.com",
        user_email="admin@example.com",
        action="set_gateway_validation_policy",
        resource_type="gateway",
        resource_id="gw-1",
        resource_name="gw",
        team_id="team-1",
        old_values={"tool_validation_policy": None},
        new_values={"tool_validation_policy": "true"},
        changes={"tool_validation_policy": {"old": None, "new": "true"}},
    )
