# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_llm_admin_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the LLM admin UI router (issue #6134).
"""

# Standard
import importlib
import sys

# Third-Party
import pytest
from fastapi import HTTPException

# Pattern B — see "Test Isolation Patterns" above.
sys.modules.pop("mcpgateway.routers.llm_admin_router", None)

# First-Party
llm_admin_router = importlib.import_module("mcpgateway.routers.llm_admin_router")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

GUARDED = (
    "get_providers_partial",
    "get_models_partial",
    "set_provider_state_html",
    "check_provider_health",
    "delete_provider_html",
    "set_model_state_html",
    "delete_model_html",
    "get_api_info_partial",
    "admin_test_api",
    "get_provider_defaults",
    "get_provider_configs",
    "fetch_provider_models",
    "sync_provider_models",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied(token_teams):
    """A narrowed admin token cannot read the LLM provider admin partial."""
    with pytest.raises(HTTPException) as exc:
        await llm_admin_router.get_provider_configs(
            current_user_ctx=admin_user_context(token_teams),
            request=scoped_request(token_teams, path="/admin/llm/provider-configs"),
        )
    assert exc.value.status_code == 403


def test_all_llm_admin_routes_carry_both_guards():
    """All 13 endpoints keep their permission decorator and gain the scope guard."""
    for name in GUARDED:
        endpoint = getattr(llm_admin_router, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == "admin.system_config", f"{name} lost its permission decorator"
    assert len(GUARDED) == 13
