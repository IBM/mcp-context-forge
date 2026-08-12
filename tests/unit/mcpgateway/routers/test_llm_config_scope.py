# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_llm_config_scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope enforcement for the LLM config router (issue #6134).
"""

# Standard
import importlib
import sys
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import HTTPException

# Rebind fresh: another suite may have imported this module under RBAC mocks;
# pop and re-import so this file always binds freshly-applied, REAL decorators
# regardless of collection order.
sys.modules.pop("mcpgateway.routers.llm_config_router", None)

# First-Party
llm_config_router = importlib.import_module("mcpgateway.routers.llm_config_router")
from tests.helpers.scope import admin_user_context, scoped_request  # noqa: E402

GUARDED = (
    "create_provider",
    "list_providers",
    "get_provider",
    "update_provider",
    "delete_provider",
    "set_provider_state",
    "check_provider_health",
    "create_model",
    "list_models",
    "get_model",
    "update_model",
    "delete_model",
    "set_model_state",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("token_teams", [["team-a"], []])
async def test_narrowed_and_public_only_are_denied(token_teams):
    """A narrowed admin token cannot list platform-wide LLM providers."""
    with pytest.raises(HTTPException) as exc:
        await llm_config_router.list_providers(
            current_user_ctx=admin_user_context(token_teams),
            db=MagicMock(),
            request=scoped_request(token_teams, path="/llm/providers"),
        )
    assert exc.value.status_code == 403


def test_all_llm_config_routes_carry_both_guards():
    """All 13 endpoints keep their permission decorator and gain the scope guard."""
    for name in GUARDED:
        endpoint = getattr(llm_config_router, name)
        assert getattr(endpoint, "__mcpgateway_scope_class__", None) == "global_only", f"{name} is missing the guard"
        assert getattr(endpoint, "_required_permission", None) == "admin.system_config", f"{name} lost its permission decorator"
    assert len(GUARDED) == 13
