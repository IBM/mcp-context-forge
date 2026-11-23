# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/alembic/versions/f2c3d4e5a6b7_translate_jsonpath_filters_to_cel.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Translate stored tool jsonpath_filter values from jq to CEL.

The filter is now a CEL expression that sees the tool response as ``response``.
The jq shapes that cover ordinary field extraction are rewritten in place:
``.``, dotted paths such as ``.a.b``, an index such as ``.[0]``, and one
``[]`` such as ``.items[].name``. jq returned every result wrapped in a list,
so a rewritten single-value path keeps that wrapping: ``.a`` becomes
``[response.a]``, while ``.items[].name`` becomes
``response.items.map(x, x.name)``, which is already a list. Any other filter,
including a path through a field named after a CEL keyword, is left as stored
and listed in a warning; the tool reports an error on every call until the
filter is rewritten in CEL.

Revision ID: f2c3d4e5a6b7
Revises: 7ac83e50bd12
Create Date: 2026-11-12 10:00:00.000000
"""

# Standard
import logging
import re
from typing import Optional, Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f2c3d4e5a6b7"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "u5e6f7a8b9c0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)

RESPONSE = "response"
LOOP_VARIABLE = "x"

# Field names CEL cannot parse after a dot.
_CEL_KEYWORDS = frozenset({"true", "false", "null", "in"})

_JQ_SEGMENT = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]|\[\]")
_CEL_PATH = r"(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*"
_CEL_SHAPE = re.compile(rf"^(?:\[{RESPONSE}({_CEL_PATH})\]|{RESPONSE}({_CEL_PATH})(?:\.map\({LOOP_VARIABLE}, {LOOP_VARIABLE}({_CEL_PATH})\))?)$")


def jq_to_cel(expression: str) -> Optional[str]:
    """Translate a simple jq path into the equivalent CEL expression.

    Args:
        expression: The stored jq filter.

    Returns:
        The CEL expression, or None when the filter is not one of the simple shapes.
    """
    text = expression.strip()
    if text == ".":
        return f"[{RESPONSE}]"
    if not text.startswith("."):
        return None
    body = text[1:] if text.startswith(".[") else text

    segments = []
    position = 0
    while position < len(body):
        match = _JQ_SEGMENT.match(body, position)
        if match is None:
            return None
        position = match.end()
        if match.group(1):
            if match.group(1) in _CEL_KEYWORDS:
                return None
            segments.append("." + match.group(1))
        elif match.group(2) is not None:
            segments.append("[" + match.group(2) + "]")
        else:
            segments.append(None)

    if segments.count(None) > 1:
        return None
    if None not in segments:
        return f"[{RESPONSE}{''.join(segments)}]"

    each = segments.index(None)
    head = RESPONSE + "".join(segments[:each])
    rest = "".join(segments[each + 1 :])
    if not rest:
        return head
    return f"{head}.map({LOOP_VARIABLE}, {LOOP_VARIABLE}{rest})"


def _jq_path(path: str) -> str:
    """Give a CEL path its jq spelling, which needs a dot before a leading index.

    Args:
        path: A CEL path such as ``.a[0]`` or ``[0].b``.

    Returns:
        The jq path.
    """
    return "." + path if path.startswith("[") else path


def cel_to_jq(expression: str) -> Optional[str]:
    """Reverse :func:`jq_to_cel` for the shapes it produces.

    Args:
        expression: The stored CEL filter.

    Returns:
        The jq filter, or None when the expression is not one of the translated shapes.
    """
    match = _CEL_SHAPE.match(expression.strip())
    if match is None:
        return None
    wrapped, head, rest = match.groups()
    if wrapped is not None:
        return _jq_path(wrapped) or "."
    return (_jq_path(head) or ".") + "[]" + (rest or "")


def _tools_table(bind: sa.Connection) -> Optional[sa.TableClause]:
    """Return the tools table when it carries a jsonpath_filter column.

    Args:
        bind: The migration connection.

    Returns:
        The table clause, or None on a database without it.
    """
    inspector = sa.inspect(bind)
    if "tools" not in inspector.get_table_names():
        return None
    if "jsonpath_filter" not in {column["name"] for column in inspector.get_columns("tools")}:
        return None
    return sa.table("tools", sa.column("id", sa.String()), sa.column("name", sa.String()), sa.column("jsonpath_filter", sa.Text()))


def _rewrite(translate, skip_prefix: str, direction: str) -> None:
    """Rewrite every stored filter with ``translate`` and warn about the rest.

    Args:
        translate: ``jq_to_cel`` or ``cel_to_jq``.
        skip_prefix: Filters starting with this are already in the target language and left alone.
        direction: Wording for the warning.
    """
    bind = op.get_bind()
    tools = _tools_table(bind)
    if tools is None:
        return

    rows = bind.execute(sa.select(tools.c.id, tools.c.name, tools.c.jsonpath_filter).where(tools.c.jsonpath_filter.is_not(None), tools.c.jsonpath_filter != "")).all()
    left = []
    for row in rows:
        stored = row.jsonpath_filter.strip()
        if not stored or stored == skip_prefix or stored.startswith(skip_prefix + ".") or stored.startswith(skip_prefix + "["):
            continue
        translated = translate(stored)
        if translated is None:
            left.append((row.name, row.id, stored))
            continue
        bind.execute(tools.update().where(tools.c.id == row.id).values(jsonpath_filter=translated))

    for name, tool_id, stored in left:
        logger.warning("Tool %r (id %s) has a jsonpath_filter that could not be translated to %s and must be rewritten by hand: %r", name, tool_id, direction, stored)


def upgrade() -> None:
    """Rewrite simple jq filters as CEL expressions over ``response``."""
    _rewrite(jq_to_cel, RESPONSE, "CEL")


def downgrade() -> None:
    """Rewrite the translated CEL expressions back to jq."""
    _rewrite(cel_to_jq, ".", "jq")
