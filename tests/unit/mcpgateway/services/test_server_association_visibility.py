# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_server_association_visibility.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Deny-path tests for tool, resource and prompt attachments on virtual servers (#7684).
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.server_service import (
    ServerError,
    _require_visible_prompts,
    _require_visible_resources,
    _require_visible_tools,
)

T1 = "item-1"
T2 = "item-2"

_CASES = (
    ("tool", _require_visible_tools),
    ("resource", _require_visible_resources),
    ("prompt", _require_visible_prompts),
)


def _scoped_item(item_id, visibility, team_id=None, owner_email=None):
    """Build a stand-in with the visibility fields the access helpers read."""
    return SimpleNamespace(id=item_id, visibility=visibility, team_id=team_id, owner_email=owner_email)


def _db_returning(*rows):
    """Return a session whose execute().scalars().all() yields the given rows."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = list(rows)
    return db


@pytest.fixture(autouse=True)
def _caller_is_not_admin():
    """Treat every caller as a non-admin in the type-specific access helpers."""
    with (
        patch("mcpgateway.services.tool_service.is_user_admin", return_value=False),
        patch("mcpgateway.services.resource_service.is_user_admin", return_value=False),
        patch("mcpgateway.services.prompt_service.is_user_admin", return_value=False),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_public_item_is_allowed_for_a_public_only_token(_kind, require_visible):
    """A public item is visible to a public-only token."""
    await require_visible(_db_returning(_scoped_item(T1, "public")), [T1], "user@example.com", [])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_item_from_another_team_is_denied(_kind, require_visible):
    """A team item from another team cannot be attached."""
    item = _scoped_item(T1, "team", team_id="team-b")

    with pytest.raises(ServerError) as exc:
        await require_visible(_db_returning(item), [T1], "user@example.com", ["team-a"])

    assert "do not exist" in str(exc.value)
    assert T1 in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_item_of_the_caller_team_is_allowed(_kind, require_visible):
    """A team item from the caller's team can be attached."""
    item = _scoped_item(T1, "team", team_id="team-a")

    await require_visible(_db_returning(item), [T1], "user@example.com", ["team-a"])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_team_item_is_denied_for_a_public_only_token(_kind, require_visible):
    """A public-only token cannot attach a team item."""
    item = _scoped_item(T1, "team", team_id="team-a")

    with pytest.raises(ServerError):
        await require_visible(_db_returning(item), [T1], "user@example.com", [])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_private_item_of_another_user_is_denied(_kind, require_visible):
    """A private item owned by someone else cannot be attached."""
    item = _scoped_item(T1, "private", owner_email="owner@example.com")

    with pytest.raises(ServerError):
        await require_visible(_db_returning(item), [T1], "user@example.com", ["team-a"])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_private_item_of_the_caller_is_allowed(_kind, require_visible):
    """The owner can attach their own private item."""
    item = _scoped_item(T1, "private", owner_email="user@example.com")

    await require_visible(_db_returning(item), [T1], "user@example.com", ["team-a"])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_unknown_id_is_denied(_kind, require_visible):
    """An unknown ID is rejected."""
    with pytest.raises(ServerError) as exc:
        await require_visible(_db_returning(), [T1], "user@example.com", ["team-a"])

    assert "do not exist" in str(exc.value)
    assert T1 in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_missing_and_invisible_items_return_the_same_error(_kind, require_visible):
    """A missing ID and an invisible ID produce the same error."""
    hidden = _scoped_item(T1, "private", owner_email="owner@example.com")

    with pytest.raises(ServerError) as missing:
        await require_visible(_db_returning(), [T1], "user@example.com", ["team-a"])
    with pytest.raises(ServerError) as invisible:
        await require_visible(_db_returning(hidden), [T1], "user@example.com", ["team-a"])

    assert str(missing.value) == str(invisible.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_one_invisible_item_denies_the_whole_request(_kind, require_visible):
    """One hidden ID rejects the request even when another ID is visible."""
    visible, hidden = _scoped_item(T1, "public"), _scoped_item(T2, "team", team_id="team-b")

    with pytest.raises(ServerError):
        await require_visible(_db_returning(visible, hidden), [T1, T2], "user@example.com", ["team-a"])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_item_already_on_the_server_needs_no_new_check(_kind, require_visible):
    """An item already attached stays allowed, even if it would now be invisible."""
    attached = _scoped_item(T1, "team", team_id="team-b")

    await require_visible(_db_returning(), [T1], "user@example.com", ["team-a"], attached=[attached])


@pytest.mark.asyncio
@pytest.mark.parametrize("_kind,require_visible", _CASES)
async def test_no_ids_runs_no_query(_kind, require_visible):
    """Omitting IDs, or sending an empty list, does not query the catalog."""
    db = _db_returning()

    await require_visible(db, None, "user@example.com", [])
    await require_visible(db, [], "user@example.com", [])

    db.execute.assert_not_called()
