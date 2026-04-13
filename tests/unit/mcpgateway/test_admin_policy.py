# -*- coding: utf-8 -*-
"""Tests for policy admin endpoints in mcpgateway.admin.

Covers:
- get_policy_partial
- list_policy_rules
- add_policy_rule
- delete_policy_rule
- policy_access_endpoint
- policy_health
- policy_cache_stats
"""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
import pytest

# First-Party
from mcpgateway import admin
from mcpgateway.admin import (
    PolicyRuleCreate,
    PolicyTestRequest,
    add_policy_rule,
    delete_policy_rule,
    get_policy_partial,
    list_policy_rules,
    policy_cache_stats,
    policy_health,
    test_policy_access as policy_access_endpoint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(pdp=None):
    """Build a minimal mock Request with configurable app.state.pdp."""
    request = MagicMock(spec=Request)
    request.scope = {"root_path": ""}
    templates = MagicMock()
    templates.TemplateResponse.return_value = HTMLResponse("<html>ok</html>")
    request.app = SimpleNamespace(state=SimpleNamespace(templates=templates, pdp=pdp))
    return request


def _make_native(rules=None):
    """Build a mock native engine with a given rules list."""
    native = MagicMock()
    native._rules = rules if rules is not None else []
    return native


def _make_pdp(native=MagicMock()):
    """Build a mock PDP with the given native engine."""
    from plugins.unified_pdp.pdp_models import EngineType

    pdp = MagicMock()
    pdp._engines = {EngineType.NATIVE: native}
    pdp.cache_stats = MagicMock(return_value={"hits": 0, "misses": 0})
    pdp.health = AsyncMock(return_value=MagicMock(healthy=True, engines=[]))
    return pdp


# ---------------------------------------------------------------------------
# get_policy_partial
# ---------------------------------------------------------------------------


class TestGetPolicyPartial:
    @pytest.mark.asyncio
    async def test_returns_html_fallback_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        response = await get_policy_partial(request, db=MagicMock(), _user=None)
        assert isinstance(response, HTMLResponse)
        assert b"not initialised" in response.body

    @pytest.mark.asyncio
    async def test_calls_template_response_when_pdp_is_set(self):
        from plugins.unified_pdp.pdp_models import EngineType

        native = _make_native(rules=[{"id": "r1"}])
        pdp = MagicMock()
        pdp._engines = {EngineType.NATIVE: native}
        pdp.cache_stats = MagicMock(return_value={})
        pdp.health = AsyncMock(return_value=MagicMock())

        request = _make_request(pdp=pdp)
        response = await get_policy_partial(request, db=MagicMock(), _user=None)

        request.app.state.templates.TemplateResponse.assert_called_once()
        _, kwargs_or_args = request.app.state.templates.TemplateResponse.call_args
        # TemplateResponse is called as positional; check context dict
        call_args = request.app.state.templates.TemplateResponse.call_args[0]
        context = call_args[2] if len(call_args) >= 3 else request.app.state.templates.TemplateResponse.call_args[1].get("context", {})
        assert context.get("rule_count") == 1

    @pytest.mark.asyncio
    async def test_uses_empty_rules_when_native_engine_absent(self):
        from plugins.unified_pdp.pdp_models import EngineType

        pdp = MagicMock()
        pdp._engines = {}  # no NATIVE engine
        pdp.cache_stats = MagicMock(return_value={})
        pdp.health = AsyncMock(return_value=MagicMock())

        request = _make_request(pdp=pdp)
        await get_policy_partial(request, db=MagicMock(), _user=None)

        call_args = request.app.state.templates.TemplateResponse.call_args[0]
        context = call_args[2]
        assert context["rule_count"] == 0
        assert context["rules"] == []


# ---------------------------------------------------------------------------
# list_policy_rules
# ---------------------------------------------------------------------------


class TestListPolicyRules:
    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await list_policy_rules(request, _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_returns_rules_from_native_engine(self):
        native = _make_native(rules=[{"id": "r1"}, {"id": "r2"}])
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        response = await list_policy_rules(request, _user=None)
        data = response.body
        import json

        parsed = json.loads(data)
        assert parsed["total"] == 2
        assert len(parsed["rules"]) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_native_engine(self):
        from plugins.unified_pdp.pdp_models import EngineType

        pdp = MagicMock()
        pdp._engines = {}  # NATIVE key absent → native=None
        request = _make_request(pdp=pdp)

        response = await list_policy_rules(request, _user=None)
        import json

        parsed = json.loads(response.body)
        assert parsed["total"] == 0
        assert parsed["rules"] == []


# ---------------------------------------------------------------------------
# add_policy_rule
# ---------------------------------------------------------------------------


class TestAddPolicyRule:
    def _rule(self, rule_id="rule-1", reason=""):
        return PolicyRuleCreate(
            id=rule_id,
            roles=["admin"],
            actions=["read"],
            resource_types=["tool"],
            resource_ids=["*"],
            reason=reason,
        )

    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await add_policy_rule(request, rule=self._rule(), _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_503_when_native_engine_absent(self):
        from plugins.unified_pdp.pdp_models import EngineType

        pdp = MagicMock()
        pdp._engines = {}  # no NATIVE
        request = _make_request(pdp=pdp)

        with pytest.raises(HTTPException) as exc_info:
            await add_policy_rule(request, rule=self._rule(), _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_409_on_duplicate_rule_id(self):
        native = _make_native(rules=[{"id": "rule-1"}])
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        with pytest.raises(HTTPException) as exc_info:
            await add_policy_rule(request, rule=self._rule(rule_id="rule-1"), _user=None)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_creates_rule_and_returns_201(self):
        import json

        native = _make_native(rules=[])
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        response = await add_policy_rule(request, rule=self._rule(rule_id="new-rule"), _user=None)
        assert response.status_code == 201
        body = json.loads(response.body)
        assert body["status"] == "created"
        assert body["id"] == "new-rule"
        native.add_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_includes_reason_in_rule_dict_when_set(self):
        native = _make_native(rules=[])
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        await add_policy_rule(request, rule=self._rule(rule_id="r2", reason="for auditing"), _user=None)

        call_kwargs = native.add_rule.call_args[0][0]
        assert call_kwargs["reason"] == "for auditing"

    @pytest.mark.asyncio
    async def test_omits_reason_from_rule_dict_when_empty(self):
        native = _make_native(rules=[])
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        await add_policy_rule(request, rule=self._rule(rule_id="r3", reason=""), _user=None)

        call_kwargs = native.add_rule.call_args[0][0]
        assert "reason" not in call_kwargs


# ---------------------------------------------------------------------------
# delete_policy_rule
# ---------------------------------------------------------------------------


class TestDeletePolicyRule:
    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await delete_policy_rule(rule_id="r1", request=request, _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_503_when_native_engine_absent(self):
        from plugins.unified_pdp.pdp_models import EngineType

        pdp = MagicMock()
        pdp._engines = {}
        request = _make_request(pdp=pdp)

        with pytest.raises(HTTPException) as exc_info:
            await delete_policy_rule(rule_id="r1", request=request, _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_raises_404_when_rule_not_found(self):
        native = _make_native()
        native.remove_rule = MagicMock(return_value=False)
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        with pytest.raises(HTTPException) as exc_info:
            await delete_policy_rule(rule_id="missing", request=request, _user=None)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_200_on_successful_deletion(self):
        import json

        native = _make_native()
        native.remove_rule = MagicMock(return_value=True)
        pdp = _make_pdp(native=native)
        request = _make_request(pdp=pdp)

        response = await delete_policy_rule(rule_id="r1", request=request, _user=None)
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["status"] == "deleted"
        assert body["id"] == "r1"


# ---------------------------------------------------------------------------
# policy_access_endpoint
# ---------------------------------------------------------------------------


class TestTestPolicyAccess:
    def _body(self):
        return PolicyTestRequest(
            subject_email="user@example.com",
            subject_roles=["admin"],
            action="read",
            resource_type="tool",
            resource_id="tool-1",
            ip="10.0.0.1",
        )

    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await policy_access_endpoint(request, body=self._body(), _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_returns_decision_from_pdp(self):
        import json

        decision = MagicMock()
        decision.decision.value = "allow"
        decision.reason = "has role"
        decision.matching_policies = ["p1"]
        decision.duration_ms = 3
        decision.cached = False
        decision.engine_decisions = []

        pdp = MagicMock()
        pdp.check_access = AsyncMock(return_value=decision)
        request = _make_request(pdp=pdp)

        response = await policy_access_endpoint(request, body=self._body(), _user=None)
        body = json.loads(response.body)

        assert body["decision"] == "allow"
        assert body["reason"] == "has role"
        assert body["matching_policies"] == ["p1"]
        assert body["duration_ms"] == 3
        assert body["cached"] is False
        assert body["engine_decisions"] == []

    @pytest.mark.asyncio
    async def test_engine_decisions_are_serialised(self):
        import json

        ed = MagicMock()
        ed.engine.value = "native"
        ed.decision.value = "allow"
        ed.reason = "ok"
        ed.matching_policies = ["p2"]

        decision = MagicMock()
        decision.decision.value = "allow"
        decision.reason = ""
        decision.matching_policies = []
        decision.duration_ms = 1
        decision.cached = True
        decision.engine_decisions = [ed]

        pdp = MagicMock()
        pdp.check_access = AsyncMock(return_value=decision)
        request = _make_request(pdp=pdp)

        response = await policy_access_endpoint(request, body=self._body(), _user=None)
        body = json.loads(response.body)

        assert len(body["engine_decisions"]) == 1
        assert body["engine_decisions"][0]["engine"] == "native"
        assert body["engine_decisions"][0]["decision"] == "allow"


# ---------------------------------------------------------------------------
# policy_health
# ---------------------------------------------------------------------------


class TestPolicyHealth:
    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await policy_health(request, _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_returns_health_report(self):
        import json

        engine_status = MagicMock()
        engine_status.engine.value = "native"
        engine_status.status.value = "healthy"
        engine_status.latency_ms = 1.2
        engine_status.detail = "ok"

        health = MagicMock()
        health.healthy = True
        health.engines = [engine_status]

        pdp = MagicMock()
        pdp.health = AsyncMock(return_value=health)
        request = _make_request(pdp=pdp)

        response = await policy_health(request, _user=None)
        body = json.loads(response.body)

        assert body["healthy"] is True
        assert len(body["engines"]) == 1
        assert body["engines"][0]["engine"] == "native"
        assert body["engines"][0]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_returns_empty_engines_list_when_no_engines(self):
        import json

        health = MagicMock()
        health.healthy = True
        health.engines = []

        pdp = MagicMock()
        pdp.health = AsyncMock(return_value=health)
        request = _make_request(pdp=pdp)

        response = await policy_health(request, _user=None)
        body = json.loads(response.body)
        assert body["engines"] == []


# ---------------------------------------------------------------------------
# policy_cache_stats
# ---------------------------------------------------------------------------


class TestPolicyCacheStats:
    @pytest.mark.asyncio
    async def test_raises_503_when_pdp_is_none(self):
        request = _make_request(pdp=None)
        with pytest.raises(HTTPException) as exc_info:
            await policy_cache_stats(request, _user=None)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_returns_cache_stats_from_pdp(self):
        import json

        stats = {"hits": 42, "misses": 7, "size": 10}
        pdp = MagicMock()
        pdp.cache_stats = MagicMock(return_value=stats)
        request = _make_request(pdp=pdp)

        response = await policy_cache_stats(request, _user=None)
        body = json.loads(response.body)

        assert body["hits"] == 42
        assert body["misses"] == 7
        assert body["size"] == 10
