# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_team_filter_public_rows.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Admin list endpoints must not suppress globally-public rows when filtering by team.

The hand-built queries in ``mcpgateway.admin`` used to gate the globally-public
condition behind ``include_public``, which nothing on the main resource tables
ever set - so selecting a team hid other teams' public rows, contradicting the
service-layer semantics. These tests pin the two halves of the contract:

* the shared rule itself (:func:`team_scoped_conditions`), in both modes, and
* that every admin call site actually routes through it rather than
  re-implementing the conditions inline.
"""

# Future
from __future__ import annotations

# Standard
import pathlib
import re

# Third-Party
import pytest
from sqlalchemy import or_, select

# First-Party
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.base_service import team_scoped_conditions

MODELS = [DbTool, DbGateway, DbResource, DbPrompt, DbServer, DbA2AAgent]
ADMIN_SRC = pathlib.Path(__file__).resolve().parents[3] / "mcpgateway" / "admin.py"


def _where(model, **kwargs) -> str:
    """Compile the WHERE clause produced by the shared conditions.

    Args:
        model: SQLAlchemy model to build against.
        **kwargs: Passed through to :func:`team_scoped_conditions`.

    Returns:
        The compiled WHERE clause as a string.
    """
    query = select(model).where(or_(*team_scoped_conditions(model, "team-1", **kwargs)))
    return str(query.compile(compile_kwargs={"literal_binds": True})).split("WHERE", 1)[1]


@pytest.mark.parametrize("model", MODELS, ids=[m.__name__ for m in MODELS])
def test_public_rows_included_by_default(model):
    """Filtering by team keeps globally-public rows from other teams.

    Args:
        model: SQLAlchemy model under test.
    """
    where = _where(model, owner_email="me@example.com")
    table = model.__tablename__
    assert f"{table}.team_id = 'team-1'" in where, "should still narrow to the requested team"
    assert f"OR {table}.visibility = 'public'" in where, "globally-public rows must not be suppressed"


@pytest.mark.parametrize("model", MODELS, ids=[m.__name__ for m in MODELS])
def test_public_rows_suppressed_only_on_explicit_opt_out(model):
    """include_public=False narrows to the team, for the UI's team-only toggle.

    Args:
        model: SQLAlchemy model under test.
    """
    where = _where(model, owner_email="me@example.com", include_public=False)
    table = model.__tablename__
    assert f"{table}.team_id = 'team-1'" in where
    assert f"OR {table}.visibility = 'public'" not in where, "explicit opt-out must drop the standalone public condition"


def test_no_admin_endpoint_rebuilds_the_conditions_inline():
    """Admin queries must route through the shared helper, not hand-rolled lists.

    The inline ``team_access = [...]`` blocks are what drifted from the service
    layer in the first place; re-introducing one would silently reopen the bug.
    """
    src = ADMIN_SRC.read_text()
    assert "team_access = [" not in src, "found a hand-rolled team-access block; use team_scoped_conditions() instead"
    assert src.count("team_scoped_conditions(") >= 19, "expected every team-filtered admin query to use the shared helper"


def test_opt_out_is_only_honoured_where_the_ui_exposes_it():
    """Only endpoints declaring include_public may pass the opt-out through.

    Endpoints without the parameter must always include public rows, so a
    stray ``include_public=`` there would be reading an undefined name.
    """
    src = ADMIN_SRC.read_text()
    declaring = src.count("include_public: Optional[bool] = None")
    passing = len(re.findall(r"team_scoped_conditions\([^)]*include_public=", src))
    assert declaring == passing, f"{declaring} endpoints declare include_public but {passing} pass it through"
