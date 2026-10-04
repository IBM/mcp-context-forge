# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_header_annotation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

x-mcp-header annotation for MCP 2026-07-28 (SEP-2243).

The spec constrains x-mcp-header to properties of primitive type
(string, integer, boolean — not number), statically reachable from the
schema root, with a value that satisfies RFC 9110 field-name token
syntax. See the spec at
https://modelcontextprotocol.io/specification/2026-07-28/server/tools#x-mcp-header.

Accumulation model: a tool's effective annotation set unions its native
schema annotations, the owning Gateway's forced_header_params, every
including Virtual Server's forced_header_params, and rule-catalog
``args.*`` references. The union is per-tool: one gateway's forced
params never leak into another gateway's tools.
"""

# Standard
import logging
import re
from typing import Optional

# Third-Party
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# RFC 9110 field-name token: visible ASCII, no separators or CTLs
_TOKEN_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

_PRIMITIVE_TYPES = frozenset({"string", "integer", "boolean"})


def _is_valid_annotation(name: str, prop_schema: dict) -> bool:
    """Check one property against the spec constraints.

    Args:
        name: The parameter name.
        prop_schema: The property's JSON Schema node.

    Returns:
        True when x-mcp-header may be applied to this property.
    """
    if not name or not _TOKEN_RE.match(name):
        return False
    prop_type = prop_schema.get("type")
    if isinstance(prop_type, list):
        return any(t in _PRIMITIVE_TYPES for t in prop_type)
    return prop_type in _PRIMITIVE_TYPES


def annotate_schema(input_schema: Optional[dict], arg_names: set[str]) -> dict:
    """Inject x-mcp-header annotations into a tool input schema.

    Only annotates properties that exist in the schema AND satisfy the
    spec constraints. Preserves any native x-mcp-header already present.
    Returns the schema unchanged when no annotations apply.

    Args:
        input_schema: The tool inputSchema as a dict.
        arg_names: Parameter names to annotate.

    Returns:
        The schema with x-mcp-header annotations injected, or the
        original schema when nothing changed.
    """
    if not input_schema or not isinstance(input_schema, dict) or not arg_names:
        return input_schema or {}
    props = input_schema.get("properties")
    if not isinstance(props, dict):
        return input_schema
    changed = False
    new_props = dict(props)
    for name in arg_names:
        if name not in new_props:
            continue
        node = new_props[name]
        if not isinstance(node, dict) or "x-mcp-header" in node:
            continue
        if not _is_valid_annotation(name, node):
            logger.debug("Skipping x-mcp-header for %s: fails spec constraints", name)
            continue
        new_props[name] = {**node, "x-mcp-header": name}
        changed = True
    if not changed:
        return input_schema
    return {**input_schema, "properties": new_props}


def collect_params_for_tool(db: Session, tool_name: str) -> set[str]:
    """Collect the x-mcp-header parameter names for one tool.

    Unions the tool's native annotations, the owning gateway's forced
    params, every including virtual server's forced params, and
    rule-catalog ``args.*`` references scoped to the tool or type-wide.

    Args:
        db: Database session.
        tool_name: The tool's registered name.

    Returns:
        The set of parameter names that should carry x-mcp-header for
        this tool. Empty when the tool has no annotations.
    """
    # First-Party
    from mcpgateway.db import Gateway, Server, Tool, server_tool_association  # pylint: disable=import-outside-toplevel
    from mcpgateway.services.rule_catalog_service import RuleCatalogService  # pylint: disable=import-outside-toplevel

    names: set[str] = set()

    # Rule-catalog references (tool-scoped and type-wide)
    try:
        names |= RuleCatalogService(db).argument_parameters_for("tool", tool_name)
        names |= RuleCatalogService(db).argument_parameters_for("tool")
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Rule catalog query skipped for %s", tool_name, exc_info=True)

    try:
        tool = db.execute(sa_select(Tool).where(Tool.name == tool_name)).scalar_one_or_none()
        if tool is None:
            return names

        # Native annotations already in the schema
        if isinstance(tool.input_schema, dict):
            for prop in tool.input_schema.get("properties", {}).values():
                if isinstance(prop, dict) and "x-mcp-header" in prop:
                    header_name = prop["x-mcp-header"]
                    if isinstance(header_name, str) and header_name:
                        names.add(header_name)

        # Owning gateway's forced params
        if tool.gateway_id:
            gw = db.get(Gateway, tool.gateway_id)
            if gw and isinstance(gw.forced_header_params, list):
                names.update(str(p) for p in gw.forced_header_params if p)

        # Every including virtual server's forced params
        server_ids = db.execute(sa_select(server_tool_association.c.server_id).where(server_tool_association.c.tool_id == tool.id)).scalars().all()
        for sid in server_ids:
            sv = db.get(Server, sid)
            if sv and isinstance(sv.forced_header_params, list):
                names.update(str(p) for p in sv.forced_header_params if p)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Per-tool header params query skipped for %s", tool_name, exc_info=True)

    return names
