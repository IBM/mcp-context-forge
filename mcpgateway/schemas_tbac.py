# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/schemas_tbac.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Pydantic schemas for task-based access control (TBAC) claims.
"""

# Standard
from typing import Dict, List, Literal

# Third-Party
from pydantic import BaseModel, ConfigDict, Field


ComparisonOperator = Literal["==", "!=", "<", "<=", ">", ">=", "in", "contains", "startswith", "endswith", "regex"]


class TBACTransactionConstraint(BaseModel):
    """Single TBAC transaction rule evaluated against an MCP request.

    Both ``left`` and ``right`` support template references like
    ``${jwt.max_limit}`` or ``${mcp.params.arguments.amount}``.
    """

    model_config = ConfigDict(extra="ignore")

    left: str = Field(description="Left operand; supports template references")
    operator: ComparisonOperator = Field(description="Comparison operator")
    right: str = Field(description="Right operand; supports template references")
    message: str = Field(default="Transaction policy violation", description="Error message when rule fails")


class TBACServerToolPolicy(BaseModel):
    """Hierarchical tool policy for a specific logical MCP server."""

    model_config = ConfigDict(extra="ignore")

    actions: List[str] = Field(default_factory=list, description="Allowed actions for server-scoped tools")
    tools: List[str] = Field(default_factory=list, description="Explicitly allowed full tool names")


class TBACClaims(BaseModel):
    """JWT TBAC claims extracted from bearer token payload."""

    model_config = ConfigDict(extra="ignore")

    authorized_tasks: List[str] = Field(default_factory=list, description="Business tasks/objectives the caller is allowed to execute")
    allowed_tools: List[str] = Field(default_factory=list, description="Flat list of allowed tool names")
    tools: Dict[str, TBACServerToolPolicy] = Field(default_factory=dict, description="Hierarchical server->actions/tools map")
    transaction_constraints: List[TBACTransactionConstraint] = Field(default_factory=list, description="Argument-level constraints evaluated during tools/call")
