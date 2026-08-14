# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/scope.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-1 scope fixtures for route-level tests.

Route tests that override ``get_current_user_with_permissions`` with a bare dict
resolve to public-only, because ``get_rpc_filter_context()`` falls back to
``normalize_token_teams()`` on an absent JWT payload. Use these helpers so the
three admin contexts the spec requires — unrestricted, team-scoped, public-only —
are constructed identically everywhere.
"""

# Standard
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock


def admin_user_context(token_teams: Optional[List[str]], email: str = "admin@example.com") -> Dict[str, Any]:
    """Build a user context dict for an admin at a given Layer-1 scope.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        email: Caller identity.

    Returns:
        Dict[str, Any]: User context in the shape route decorators expect.
    """
    return {"email": email, "full_name": "Test Admin", "is_admin": True, "token_teams": token_teams, "db": None}


def scoped_request(token_teams: Optional[List[str]], path: str = "/") -> MagicMock:
    """Build a request whose resolved Layer-1 scope is ``token_teams``.

    Args:
        token_teams: ``None`` for unrestricted, ``[]`` for public-only, or a list of team IDs.
        path: Route path, used by denial logging assertions.

    Returns:
        MagicMock: Request stub with ``state.token_teams`` and ``url.path`` set.
    """
    request = MagicMock()
    request.state = SimpleNamespace(token_teams=token_teams)
    request.url = SimpleNamespace(path=path)
    return request
