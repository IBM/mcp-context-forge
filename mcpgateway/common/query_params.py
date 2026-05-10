# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/common/query_params.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Shared FastAPI query-parameter aliases to centralize regex-backed validation.

These aliases intentionally preserve endpoint-level OpenAPI parameter metadata
(patterns, length caps, and descriptions) while reducing duplicated inline
``Query(pattern=...)`` declarations across routers.
"""

# Standard
from typing import Annotated, Optional

# Third-Party
from fastapi import Query

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings

QueryPaginationCursor = Annotated[
    Optional[str],
    Query(
        max_length=500,
        pattern=settings.validation_cursor_pattern,
        description="Cursor for pagination",
    ),
]

QueryPaginationCursorGeneric = Annotated[
    Optional[str],
    Query(
        max_length=500,
        pattern=settings.validation_cursor_pattern,
        description="Pagination cursor",
    ),
]

QueryPaginationCursorResults = Annotated[
    Optional[str],
    Query(
        max_length=500,
        pattern=settings.validation_cursor_pattern,
        description="Pagination cursor for fetching the next set of results",
    ),
]

QueryTagsFilter = Annotated[
    Optional[str],
    Query(
        max_length=500,
        pattern=settings.validation_tags_filter_pattern,
        description="Tag filter expression (comma=OR, plus=AND)",
    ),
]

QueryGatewayIdList = Annotated[
    Optional[str],
    Query(
        max_length=1000,
        pattern=settings.validation_gateway_id_list_pattern,
        description="Filter by gateway ID(s), comma-separated",
    ),
]

QueryRenderMode = Annotated[
    Optional[str],
    Query(
        max_length=50,
        pattern=settings.validation_render_mode_pattern,
    ),
]

QueryRenderModeControls = Annotated[
    Optional[str],
    Query(
        max_length=50,
        pattern=settings.validation_render_mode_pattern,
        description="Render mode: 'controls' for pagination controls only",
    ),
]

QueryRenderModeUserSelector = Annotated[
    Optional[str],
    Query(
        max_length=50,
        pattern=settings.validation_render_mode_pattern,
        description="Render mode: 'selector' for user selector items, 'controls' for pagination controls",
    ),
]

QueryVisibility = Annotated[
    Optional[str],
    Query(
        pattern=settings.validation_visibility_pattern,
        description="Filter by visibility: private, team, public",
    ),
]

QueryVisibilityCompact = Annotated[
    Optional[str],
    Query(
        pattern=settings.validation_visibility_pattern,
        description="Filter by visibility",
    ),
]

QueryUserIdentifier = Annotated[
    Optional[str],
    Query(
        max_length=255,
        pattern=settings.validation_user_identifier_pattern,
        description="Filter by user email or service-account identifier",
    ),
]

QueryUserIdentifierNoDescription = Annotated[
    Optional[str],
    Query(
        max_length=255,
        pattern=settings.validation_user_identifier_pattern,
    ),
]

QueryHttpMethod = Annotated[
    Optional[str],
    Query(
        pattern=settings.validation_http_method_pattern,
        description="Filter by HTTP method",
    ),
]

QueryExportFormat = Annotated[
    str,
    Query(
        pattern=settings.validation_export_format_pattern,
        description="Export format (json, csv, ndjson)",
    ),
]

QueryExportFormatAliased = Annotated[
    str,
    Query(
        alias="format",
        pattern=settings.validation_export_format_pattern,
    ),
]

QueryToolName = Annotated[
    Optional[str],
    Query(
        max_length=255,
        pattern=SecurityValidator.TOOL_NAME_PATTERN,
    ),
]

QueryErrorCode = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_error_code_pattern,
        description="OAuth provider error code",
    ),
]

QueryErrorCodeSso = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_error_code_pattern,
        description="OAuth error code",
    ),
]

QueryIdentifierDotted = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=SecurityValidator.IDENTIFIER_PATTERN,
        description="Filter by scope",
    ),
]

QueryIdentifierDottedComponent = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=SecurityValidator.IDENTIFIER_PATTERN,
    ),
]

QueryIdentifierDotted300 = Annotated[
    str,
    Query(
        max_length=300,
        pattern=SecurityValidator.IDENTIFIER_PATTERN,
        description="Tool ID",
    ),
]

QueryProviderId = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=SecurityValidator.IDENTIFIER_PATTERN,
        description="Filter by provider ID",
    ),
]

QueryTeamId = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_team_id_pattern,
        description="Filter by team ID",
    ),
]

QueryTeamContext = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_team_id_pattern,
        description="Team context",
    ),
]

QueryScopeId = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_scope_id_pattern,
        description="Scope ID filter",
    ),
]

QueryGatewayId = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=settings.validation_gateway_id_pattern,
        description="Filter by gateway ID",
    ),
]

QueryTraceId = Annotated[
    Optional[str],
    Query(
        max_length=128,
        pattern=settings.validation_trace_id_pattern,
        description="Filter by trace ID",
    ),
]

QueryResourceType = Annotated[
    Optional[str],
    Query(
        max_length=100,
        pattern=SecurityValidator.IDENTIFIER_PATTERN,
        description="Filter by resource type",
    ),
]

QueryResourceName = Annotated[
    Optional[str],
    Query(
        max_length=255,
        pattern=settings.validation_resource_name_pattern,
        description="Filter by resource name",
    ),
]

QueryTraceStatus = Annotated[
    Optional[str],
    Query(
        pattern=settings.validation_trace_status_pattern,
        description="Filter by status (ok, error)",
    ),
]

QueryToolOpsMode = Annotated[
    str,
    Query(
        pattern=settings.validation_toolops_mode_pattern,
        description="Three modes: 'generate' for test case generation, 'query' for obtaining test cases from DB , 'status' to check test generation status",
    ),
]

QueryRelationship = Annotated[
    Optional[str],
    Query(
        pattern=settings.validation_relationship_pattern,
        description="Filter by relationship: owner, member, public",
    ),
]

QueryEntityType = Annotated[
    str,
    Query(
        pattern=settings.validation_entity_type_pattern,
        description="Entity type: tools, resources, prompts, or servers",
    ),
]

QueryTimeRange = Annotated[
    str,
    Query(
        pattern=settings.validation_time_range_pattern,
    ),
]

QueryStatusFilter = Annotated[
    str,
    Query(
        pattern=settings.validation_status_filter_pattern,
    ),
]

QueryPeriodType = Annotated[
    str,
    Query(
        pattern=settings.validation_period_type_pattern,
        description="Aggregation period: hourly or daily",
    ),
]

QueryAggregation = Annotated[
    str,
    Query(
        pattern=settings.validation_aggregation_pattern,
        description="Aggregation level for metrics",
    ),
]

QueryEntityTypes = Annotated[
    Optional[str],
    Query(
        max_length=200,
        pattern=settings.validation_entity_types_pattern,
        description="Comma-separated entity types to include (servers,gateways,tools,resources,prompts,agents,teams,users,roots)",
    ),
]
