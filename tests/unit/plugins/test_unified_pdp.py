# -*- coding: utf-8 -*-
"""Unit tests for the Unified PDP – all engines, cache, orchestrator.

Run::

    pytest tests/unit/plugins/test_unified_pdp.py -v --tb=short

Dependencies (test-only)::

    pytest pytest-asyncio pytest-httpx httpx
"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# Adjust imports – works whether you run from repo root or this directory
# ---------------------------------------------------------------------------
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from plugins.unified_pdp import (
    PolicyDecisionPoint,
    PDPConfig,
    EngineConfig,
    CacheConfig,
    PerformanceConfig,
    Subject,
    Resource,
    Context,
    Decision,
    CombinationMode,
    EngineType,
)
from plugins.unified_pdp.pdp_models import EngineDecision, AccessDecision
from plugins.unified_pdp.engines.opa_engine import OPAEngineAdapter
from plugins.unified_pdp.engines.cedar_engine import CedarEngineAdapter
from plugins.unified_pdp.engines.native_engine import NativeRBACAdapter
from plugins.unified_pdp.engines.mac_engine import MACEngineAdapter
from plugins.unified_pdp.cache import DecisionCache, _build_cache_key
from plugins.unified_pdp.adapter import PolicyEvaluationError, PolicyEngineUnavailableError


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def subject_admin():
    return Subject(email="admin@example.com", roles=["admin"], mfa_verified=True, clearance_level=3)


@pytest.fixture
def subject_dev():
    return Subject(email="dev@example.com", roles=["developer"], mfa_verified=False, clearance_level=1)


@pytest.fixture
def resource_tool():
    return Resource(type="tool", id="db-query", server="prod-db", classification_level=2)


@pytest.fixture
def resource_public():
    return Resource(type="tool", id="time-check", classification_level=0)


@pytest.fixture
def context_basic():
    return Context(ip="10.0.0.1", session_id="sess-abc-123")


# ===========================================================================
# 1. Model validation
# ===========================================================================


class TestModels:
    def test_subject_defaults(self):
        s = Subject(email="x@y.com")
        assert s.roles == []
        assert s.mfa_verified is False
        assert s.clearance_level is None

    def test_resource_defaults(self):
        r = Resource(type="tool", id="foo")
        assert r.server is None
        assert r.classification_level is None
        assert r.annotations == {}

    def test_pdp_config_defaults(self):
        c = PDPConfig()
        assert c.combination_mode == CombinationMode.ALL_MUST_ALLOW
        assert c.default_decision == Decision.DENY
        assert c.cache.enabled is True
        assert c.performance.parallel_evaluation is True

    def test_engine_decision_serialisation(self):
        ed = EngineDecision(
            engine=EngineType.OPA,
            decision=Decision.ALLOW,
            reason="test",
            duration_ms=1.5,
        )
        raw = ed.model_dump_json()
        restored = EngineDecision.model_validate_json(raw)
        assert restored.engine == EngineType.OPA
        assert restored.decision == Decision.ALLOW


# ===========================================================================
# 2. OPA Engine Adapter
# ===========================================================================


class TestOPAEngine:
    @pytest.fixture
    def adapter(self):
        return OPAEngineAdapter(settings={"opa_url": "http://opa-mock:8181", "max_retries": 1})

    @pytest.mark.asyncio
    async def test_evaluate_allow(self, adapter, subject_admin, resource_tool, context_basic, httpx_mock):
        httpx_mock.add_response(
            url="http://opa-mock:8181/v1/data/mcpgateway",
            method="POST",
            json={"result": {"allow": True}},
        )
        decision = await adapter.evaluate(subject_admin, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.ALLOW
        assert decision.engine == EngineType.OPA
        assert decision.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_evaluate_deny_with_reasons(self, adapter, subject_dev, resource_tool, context_basic, httpx_mock):
        httpx_mock.add_response(
            url="http://opa-mock:8181/v1/data/mcpgateway",
            method="POST",
            json={"result": {"allow": False, "deny": ["MFA required", "Insufficient role"]}},
        )
        decision = await adapter.evaluate(subject_dev, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.DENY
        assert "MFA required" in decision.reason
        assert len(decision.matching_policies) == 2

    @pytest.mark.asyncio
    async def test_evaluate_undefined_result(self, adapter, subject_dev, resource_tool, context_basic, httpx_mock):
        """Empty result = undefined policy = fail closed."""
        httpx_mock.add_response(
            url="http://opa-mock:8181/v1/data/mcpgateway",
            method="POST",
            json={},
        )
        decision = await adapter.evaluate(subject_dev, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.DENY
        assert "undefined" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_evaluate_server_error_exhausts_retries(self, adapter, subject_dev, resource_tool, context_basic, httpx_mock):
        httpx_mock.add_response(
            url="http://opa-mock:8181/v1/data/mcpgateway",
            method="POST",
            status_code=500,
            text="Internal Server Error",
        )
        with pytest.raises(PolicyEvaluationError):
            await adapter.evaluate(subject_dev, "tools.invoke", resource_tool, context_basic)

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, adapter, httpx_mock):
        httpx_mock.add_response(
            url="http://opa-mock:8181/health",
            method="GET",
            json={},
        )
        report = await adapter.health_check()
        assert report.status.value == "healthy"
        assert report.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, adapter, httpx_mock):
        httpx_mock.add_response(
            url="http://opa-mock:8181/health",
            method="GET",
            status_code=503,
        )
        report = await adapter.health_check()
        assert report.status.value == "unhealthy"

    def test_build_input_structure(self, subject_admin, resource_tool, context_basic):
        inp = OPAEngineAdapter._build_input(subject_admin, "tools.invoke", resource_tool, context_basic)
        assert inp["subject"]["email"] == "admin@example.com"
        assert inp["action"] == "tools.invoke"
        assert inp["resource"]["type"] == "tool"
        assert inp["context"]["ip"] == "10.0.0.1"


# ===========================================================================
# 3. Cedar Engine Adapter
# ===========================================================================


class TestCedarEngine:
    @pytest.fixture
    def adapter(self):
        return CedarEngineAdapter(settings={"cedar_url": "http://cedar-mock:8700", "max_retries": 1})

    @pytest.mark.asyncio
    async def test_evaluate_allow(self, adapter, subject_admin, resource_tool, context_basic, httpx_mock):
        httpx_mock.add_response(
            url="http://cedar-mock:8700/v1/authorize",
            method="POST",
            json={"decision": "Allow", "reasons": []},
        )
        decision = await adapter.evaluate(subject_admin, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.ALLOW
        assert decision.engine == EngineType.CEDAR

    @pytest.mark.asyncio
    async def test_evaluate_deny(self, adapter, subject_dev, resource_tool, context_basic, httpx_mock):
        httpx_mock.add_response(
            url="http://cedar-mock:8700/v1/authorize",
            method="POST",
            json={"decision": "Deny", "reasons": ["Policy cedar-001: role developer not permitted"]},
        )
        decision = await adapter.evaluate(subject_dev, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.DENY
        assert "cedar-001" in decision.reason

    def test_build_entities(self, subject_admin):
        entities = CedarEngineAdapter._build_entities(subject_admin)
        # Should have: 1 Role entity + 1 User entity
        assert len(entities) == 2
        user_entity = next(e for e in entities if e["identifier"]["type"] == "User")
        assert user_entity["identifier"]["id"] == "admin@example.com"
        assert {"type": "Role", "id": "admin"} in user_entity["parents"]

    @pytest.mark.asyncio
    async def test_health_check(self, adapter, httpx_mock):
        httpx_mock.add_response(
            url="http://cedar-mock:8700/health",
            method="GET",
            json={},
        )
        report = await adapter.health_check()
        assert report.status.value == "healthy"


# ===========================================================================
# 4. Native RBAC Adapter
# ===========================================================================


_SAMPLE_RULES = [
    {
        "id": "allow-admin-all",
        "roles": ["admin"],
        "actions": ["*"],
        "resource_types": ["*"],
        "resource_ids": ["*"],
    },
    {
        "id": "allow-dev-read-tools",
        "roles": ["developer"],
        "actions": ["tools.list", "tools.get"],
        "resource_types": ["tool"],
        "resource_ids": ["*"],
    },
    {
        "id": "deny:no-mfa-destructive",
        "roles": ["*"],
        "actions": ["tools.delete", "tools.update"],
        "resource_types": ["tool"],
        "resource_ids": ["*"],
        "conditions": {"subject.mfa_verified": False},
        "reason": "MFA is required for destructive operations",
    },
    {
        "id": "allow-dev-invoke-non-prod",
        "roles": ["developer"],
        "actions": ["tools.invoke"],
        "resource_types": ["tool"],
        "resource_ids": ["*"],
        "conditions": {"context.ip_prefix": "10.0.0."},
    },
]


class TestNativeRBACEngine:
    @pytest.fixture
    def adapter(self):
        return NativeRBACAdapter(settings={"rules": _SAMPLE_RULES})

    @pytest.mark.asyncio
    async def test_admin_can_do_anything(self, adapter, subject_admin, resource_tool, context_basic):
        decision = await adapter.evaluate(subject_admin, "tools.invoke", resource_tool, context_basic)
        assert decision.decision == Decision.ALLOW
        assert "allow-admin-all" in decision.matching_policies

    @pytest.mark.asyncio
    async def test_dev_can_list_tools(self, adapter, subject_dev, resource_tool, context_basic):
        decision = await adapter.evaluate(subject_dev, "tools.list", resource_tool, context_basic)
        assert decision.decision == Decision.ALLOW
        assert "allow-dev-read-tools" in decision.matching_policies

    @pytest.mark.asyncio
    async def test_dev_denied_invoke_without_condition(self, adapter, context_basic):
        """Developer trying to invoke from a non-matching IP."""
        dev = Subject(email="dev@x.com", roles=["developer"], mfa_verified=False)
        ctx = Context(ip="192.168.1.1")  # not 10.0.0.*
        res = Resource(type="tool", id="anything")
        decision = await adapter.evaluate(dev, "tools.invoke", res, ctx)
        assert decision.decision == Decision.DENY

    @pytest.mark.asyncio
    async def test_deny_rule_blocks_before_allow(self, adapter, context_basic):
        """Deny rules run first – even if an allow rule would match."""
        dev_no_mfa = Subject(email="dev@x.com", roles=["developer"], mfa_verified=False)
        res = Resource(type="tool", id="db-query")
        decision = await adapter.evaluate(dev_no_mfa, "tools.delete", res, context_basic)
        assert decision.decision == Decision.DENY
        assert "MFA" in decision.reason

    @pytest.mark.asyncio
    async def test_get_permissions(self, adapter, subject_admin, context_basic):
        perms = await adapter.get_permissions(subject_admin, context_basic)
        # Admin matches the wildcard rule
        assert len(perms) >= 1
        assert any(p.action == "*" for p in perms)

    @pytest.mark.asyncio
    async def test_health_always_healthy(self, adapter):
        report = await adapter.health_check()
        assert report.status.value == "healthy"
        assert "4 rules" in report.detail

    def test_add_and_remove_rule(self, adapter):
        adapter.add_rule({"id": "temp-rule", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]})
        assert any(r["id"] == "temp-rule" for r in adapter._rules)
        removed = adapter.remove_rule("temp-rule")
        assert removed is True
        assert not any(r["id"] == "temp-rule" for r in adapter._rules)


# ===========================================================================
# 5. MAC Engine Adapter
# ===========================================================================


class TestMACEngine:
    @pytest.fixture
    def adapter(self):
        return MACEngineAdapter(settings={"relaxed_star": False})

    @pytest.fixture
    def adapter_relaxed(self):
        return MACEngineAdapter(settings={"relaxed_star": True})

    @pytest.mark.asyncio
    async def test_read_allowed_when_clearance_gte_classification(self, adapter):
        subj = Subject(email="s@x.com", roles=[], clearance_level=3)
        res = Resource(type="tool", id="secret-doc", classification_level=2)
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.get", res, ctx)
        assert decision.decision == Decision.ALLOW
        assert "read allowed" in decision.reason

    @pytest.mark.asyncio
    async def test_read_denied_when_clearance_lt_classification(self, adapter):
        subj = Subject(email="s@x.com", roles=[], clearance_level=1)
        res = Resource(type="tool", id="secret-doc", classification_level=3)
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.get", res, ctx)
        assert decision.decision == Decision.DENY
        assert "no read-up" in decision.reason

    @pytest.mark.asyncio
    async def test_write_allowed_strict_when_levels_equal(self, adapter):
        subj = Subject(email="s@x.com", roles=[], clearance_level=2)
        res = Resource(type="tool", id="doc", classification_level=2)
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.update", res, ctx)
        assert decision.decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_write_denied_strict_when_levels_differ(self, adapter):
        subj = Subject(email="s@x.com", roles=[], clearance_level=3)
        res = Resource(type="tool", id="doc", classification_level=2)
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.update", res, ctx)
        assert decision.decision == Decision.DENY
        assert "no write-down" in decision.reason

    @pytest.mark.asyncio
    async def test_write_allowed_relaxed_when_clearance_gte(self, adapter_relaxed):
        subj = Subject(email="s@x.com", roles=[], clearance_level=3)
        res = Resource(type="tool", id="doc", classification_level=2)
        ctx = Context()
        decision = await adapter_relaxed.evaluate(subj, "tools.update", res, ctx)
        assert decision.decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_denied_when_subject_has_no_clearance(self, adapter):
        subj = Subject(email="s@x.com", roles=[])  # clearance_level is None
        res = Resource(type="tool", id="doc", classification_level=1)
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.get", res, ctx)
        assert decision.decision == Decision.DENY
        assert "no clearance_level" in decision.reason

    @pytest.mark.asyncio
    async def test_denied_when_resource_has_no_classification(self, adapter):
        subj = Subject(email="s@x.com", roles=[], clearance_level=2)
        res = Resource(type="tool", id="doc")  # classification_level is None
        ctx = Context()
        decision = await adapter.evaluate(subj, "tools.get", res, ctx)
        assert decision.decision == Decision.DENY
        assert "no classification_level" in decision.reason

    @pytest.mark.asyncio
    async def test_explicit_operation_override(self, adapter):
        """Context.extra can override the read/write heuristic."""
        subj = Subject(email="s@x.com", roles=[], clearance_level=1)
        res = Resource(type="tool", id="doc", classification_level=3)
        # Action looks like a write but context says read
        ctx = Context(extra={"operation": "read"})
        decision = await adapter.evaluate(subj, "tools.update", res, ctx)
        # clearance 1 < classification 3 → read denied
        assert decision.decision == Decision.DENY
        assert "no read-up" in decision.reason


# ===========================================================================
# 6. Decision Cache
# ===========================================================================


class TestDecisionCache:
    @pytest.fixture
    def cache(self):
        return DecisionCache(CacheConfig(enabled=True, ttl_seconds=60, max_entries=3))

    @pytest.fixture
    def sample_decision(self):
        return AccessDecision(decision=Decision.ALLOW, reason="test")

    @pytest.mark.asyncio
    async def test_put_and_get(self, cache, subject_admin, resource_tool, context_basic, sample_decision):
        await cache.put(subject_admin, "tools.invoke", resource_tool, context_basic, sample_decision)
        result = await cache.get(subject_admin, "tools.invoke", resource_tool, context_basic)
        assert result is not None
        assert result.decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache, subject_dev, resource_tool, context_basic):
        result = await cache.get(subject_dev, "tools.invoke", resource_tool, context_basic)
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache, context_basic, sample_decision):
        """Cache has max_entries=3. Fourth entry should evict the first."""
        for i in range(4):
            subj = Subject(email=f"user{i}@x.com")
            res = Resource(type="tool", id=f"tool-{i}")
            await cache.put(subj, "act", res, context_basic, sample_decision)

        # First entry should be evicted
        first_subj = Subject(email="user0@x.com")
        first_res = Resource(type="tool", id="tool-0")
        assert await cache.get(first_subj, "act", first_res, context_basic) is None

        # Last entry should still be there
        last_subj = Subject(email="user3@x.com")
        last_res = Resource(type="tool", id="tool-3")
        assert await cache.get(last_subj, "act", last_res, context_basic) is not None

    @pytest.mark.asyncio
    async def test_stats(self, cache, subject_admin, resource_tool, context_basic, sample_decision):
        await cache.put(subject_admin, "act", resource_tool, context_basic, sample_decision)
        await cache.get(subject_admin, "act", resource_tool, context_basic)  # hit
        await cache.get(subject_dev_email(), "act", resource_tool, context_basic)  # miss

        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    @pytest.mark.asyncio
    async def test_disabled_cache_always_misses(self, subject_admin, resource_tool, context_basic, sample_decision):
        cache = DecisionCache(CacheConfig(enabled=False))
        await cache.put(subject_admin, "act", resource_tool, context_basic, sample_decision)
        result = await cache.get(subject_admin, "act", resource_tool, context_basic)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate(self, cache, subject_admin, resource_tool, context_basic, sample_decision):
        await cache.put(subject_admin, "act", resource_tool, context_basic, sample_decision)
        removed = await cache.invalidate()
        assert removed == 1
        assert await cache.get(subject_admin, "act", resource_tool, context_basic) is None


def subject_dev_email():
    """Helper to create a unique subject for miss tests."""
    return Subject(email="unique-miss@x.com")


# ===========================================================================
# 7. PDP Orchestrator – Combination Logic
# ===========================================================================


def _make_config(
    engines: list[EngineConfig],
    mode: CombinationMode = CombinationMode.ALL_MUST_ALLOW,
    cache_enabled: bool = False,
) -> PDPConfig:
    return PDPConfig(
        engines=engines,
        combination_mode=mode,
        default_decision=Decision.DENY,
        cache=CacheConfig(enabled=cache_enabled),
        performance=PerformanceConfig(timeout_ms=5000, parallel_evaluation=True),
    )


class TestPDPCombination:
    """Test combination logic by injecting mock engines via monkeypatch."""

    @pytest.fixture
    def native_allow_all(self):
        """Native engine that allows everything."""
        return NativeRBACAdapter(settings={
            "rules": [{"id": "allow-all", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]
        })

    @pytest.fixture
    def native_deny_all(self):
        """Native engine with no rules (denies everything)."""
        return NativeRBACAdapter(settings={"rules": []})

    @pytest.mark.asyncio
    async def test_all_must_allow_passes_when_all_allow(self):
        """Two native engines both allowing → ALLOW."""
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                         settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]}),
        ], mode=CombinationMode.ALL_MUST_ALLOW)

        pdp = PolicyDecisionPoint(config)
        decision = await pdp.check_access(
            Subject(email="u@x.com", roles=["admin"]),
            "tools.invoke",
            Resource(type="tool", id="t1"),
            Context(),
        )
        assert decision.decision == Decision.ALLOW

    @pytest.mark.asyncio
    async def test_all_must_allow_fails_when_one_denies(self):
        """Native with no rules → denies → aggregate DENY."""
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1, settings={"rules": []}),
        ], mode=CombinationMode.ALL_MUST_ALLOW)

        pdp = PolicyDecisionPoint(config)
        decision = await pdp.check_access(
            Subject(email="u@x.com", roles=["dev"]),
            "tools.invoke",
            Resource(type="tool", id="t1"),
            Context(),
        )
        assert decision.decision == Decision.DENY
        assert "all_must_allow" in decision.reason

    @pytest.mark.asyncio
    async def test_any_allow_passes_with_one_allow(self):
        """MAC denies (no clearance) but Native allows → ANY_ALLOW = ALLOW."""
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                         settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]}),
            EngineConfig(name=EngineType.MAC, enabled=True, priority=2, settings={}),
        ], mode=CombinationMode.ANY_ALLOW)

        pdp = PolicyDecisionPoint(config)
        decision = await pdp.check_access(
            Subject(email="u@x.com", roles=["admin"]),  # no clearance_level
            "tools.get",
            Resource(type="tool", id="t1"),  # no classification_level
            Context(),
        )
        assert decision.decision == Decision.ALLOW
        assert "any_allow" in decision.reason

    @pytest.mark.asyncio
    async def test_any_allow_denies_when_all_deny(self):
        """Both engines deny → ANY_ALLOW = DENY."""
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1, settings={"rules": []}),
            EngineConfig(name=EngineType.MAC, enabled=True, priority=2, settings={}),
        ], mode=CombinationMode.ANY_ALLOW)

        pdp = PolicyDecisionPoint(config)
        decision = await pdp.check_access(
            Subject(email="u@x.com", roles=[]),
            "tools.invoke",
            Resource(type="tool", id="t1"),
            Context(),
        )
        assert decision.decision == Decision.DENY

    @pytest.mark.asyncio
    async def test_first_match_uses_highest_priority(self):
        """FIRST_MATCH with Native (priority 1, allows) → stops there."""
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                         settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]}),
            EngineConfig(name=EngineType.MAC, enabled=True, priority=2, settings={}),
        ], mode=CombinationMode.FIRST_MATCH)

        pdp = PolicyDecisionPoint(config)
        # Use sequential mode so first_match short-circuit works
        pdp._config.performance.parallel_evaluation = False
        decision = await pdp.check_access(
            Subject(email="u@x.com", roles=["admin"]),
            "tools.get",
            Resource(type="tool", id="t1"),
            Context(),
        )
        assert decision.decision == Decision.ALLOW
        assert "first_match" in decision.reason


# ===========================================================================
# 8. PDP – Caching integration
# ===========================================================================


class TestPDPCaching:
    @pytest.mark.asyncio
    async def test_second_call_hits_cache(self):
        config = _make_config(
            [EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                          settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]})],
            cache_enabled=True,
        )
        pdp = PolicyDecisionPoint(config)

        subj = Subject(email="cached@x.com", roles=["admin"])
        res = Resource(type="tool", id="t1")
        ctx = Context(ip="1.2.3.4")

        first = await pdp.check_access(subj, "tools.invoke", res, ctx)
        assert first.cached is False

        second = await pdp.check_access(subj, "tools.invoke", res, ctx)
        assert second.cached is True
        assert second.decision == first.decision


# ===========================================================================
# 9. PDP – explain_decision
# ===========================================================================


class TestPDPExplain:
    @pytest.mark.asyncio
    async def test_explain_returns_all_engine_details(self):
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                         settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]}),
            EngineConfig(name=EngineType.MAC, enabled=True, priority=2, settings={}),
        ])
        pdp = PolicyDecisionPoint(config)

        explanation = await pdp.explain_decision(
            Subject(email="u@x.com", roles=["admin"], clearance_level=2),
            "tools.get",
            Resource(type="tool", id="t1", classification_level=1),
            Context(),
        )
        assert len(explanation.engine_explanations) == 2
        assert explanation.combination_mode == CombinationMode.ALL_MUST_ALLOW
        engine_names = [e["engine"] for e in explanation.engine_explanations]
        assert "native" in engine_names
        assert "mac" in engine_names


# ===========================================================================
# 10. PDP – Health
# ===========================================================================


class TestPDPHealth:
    @pytest.mark.asyncio
    async def test_health_reports_all_engines(self):
        config = _make_config([
            EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1, settings={"rules": []}),
            EngineConfig(name=EngineType.MAC, enabled=True, priority=2, settings={}),
            EngineConfig(name=EngineType.OPA, enabled=False, priority=3, settings={}),
        ])
        pdp = PolicyDecisionPoint(config)
        report = await pdp.health()

        engine_statuses = {r.engine: r.status.value for r in report.engines}
        assert engine_statuses[EngineType.NATIVE] == "healthy"
        assert engine_statuses[EngineType.MAC] == "healthy"
        assert engine_statuses[EngineType.OPA] == "disabled"


# ===========================================================================
# 11. Edge cases
# ===========================================================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_engines_configured_returns_default(self):
        config = _make_config([])
        pdp = PolicyDecisionPoint(config)
        decision = await pdp.check_access(
            Subject(email="u@x.com"),
            "tools.invoke",
            Resource(type="tool", id="t1"),
            Context(),
        )
        assert decision.decision == Decision.DENY
        assert "no engines" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_cache_stats_populated(self):
        config = _make_config(
            [EngineConfig(name=EngineType.NATIVE, enabled=True, priority=1,
                          settings={"rules": [{"id": "r1", "roles": ["*"], "actions": ["*"], "resource_types": ["*"], "resource_ids": ["*"]}]})],
            cache_enabled=True,
        )
        pdp = PolicyDecisionPoint(config)

        subj = Subject(email="stats@x.com", roles=["admin"])
        res = Resource(type="tool", id="t1")
        ctx = Context()

        await pdp.check_access(subj, "act", res, ctx)  # miss → store
        await pdp.check_access(subj, "act", res, ctx)  # hit

        stats = pdp.cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
