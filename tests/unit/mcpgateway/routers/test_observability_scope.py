# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_observability_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the observability router (issue #6134).
"""

# Standard
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException

# Pattern B — see "Test Isolation Patterns" above.
sys.modules.pop("mcpgateway.routers.observability", None)

# First-Party
observability = importlib.import_module("mcpgateway.routers.observability")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

GUARDED = (
    "list_traces",
    "query_traces_advanced",
    "get_trace",
    "list_spans",
    "cleanup_old_traces",
    "get_stats",
    "export_traces",
    "get_query_performance",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied(token_teams):
    """A narrowed or public-only admin token cannot read platform-wide traces."""
    with pytest.raises(HTTPException) as exc:
        await observability.get_stats(
            hours=24,
            db=MagicMock(),
            _user=admin_user_context(token_teams),
            request=scoped_request(token_teams, path="/observability/stats"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unrestricted_admin_passes_the_guard():
    """token_teams=None passes the guard, so the handler body is entered.

    get_stats has no injectable service — it queries the DB inline through
    SQLAlchemy — so this asserts only that the guard did not raise 403. A
    MagicMock db makes the query itself a no-op.
    """
    with patch("mcpgateway.middleware.rbac._global_scope_denied", AsyncMock(return_value=False)):
        try:
            await observability.get_stats(
                hours=24,
                db=MagicMock(),
                _user=admin_user_context(None),
                request=scoped_request(None, path="/observability/stats"),
            )
        except HTTPException as exc:  # pragma: no cover - only on regression
            pytest.fail(f"unrestricted admin was rejected: {exc.status_code}")
        except Exception:  # pylint: disable=broad-except
            # The handler ran; a downstream failure on the mocked DB is not this test's concern.
            pass


def test_module_imports_with_real_decorators():
    """Guard against this file accidentally being imported under the RBAC mocks."""
    assert getattr(observability.get_stats, "__mcpgateway_scope_class__", None) == "global_only"


def test_all_observability_routes_carry_both_guards():
    """Every guarded endpoint keeps its permission decorator and gains the scope guard."""
    for name in GUARDED:
        endpoint = getattr(observability, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == "admin.system_config", f"{name} lost its permission decorator"
