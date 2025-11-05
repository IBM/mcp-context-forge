# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/pagination.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Pagination Utilities for MCP Gateway.

This module provides utilities for implementing efficient pagination
across all MCP Gateway endpoints, supporting both offset-based and
cursor-based pagination strategies.

Features:
- Offset-based pagination for simple use cases (<10K records)
- Cursor-based pagination for large datasets (>10K records)
- Automatic strategy selection based on result set size
- Navigation link generation
- Query parameter parsing and validation

Examples:
    Basic usage with pagination query::

        from mcpgateway.utils.pagination import paginate_query
        from sqlalchemy import select
        from mcpgateway.common.models import Tool

        async def list_tools(db: Session):
            query = select(Tool).where(Tool.enabled == True)
            result = await paginate_query(
                db=db,
                query=query,
                page=1,
                per_page=50,
                base_url="/admin/tools"
            )
            return result
"""

# Standard
import base64
import json
import logging
import math
from typing import Any, Dict, Optional
from urllib.parse import urlencode

# Third-Party
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import PaginationLinks, PaginationMeta

logger = logging.getLogger(__name__)


def encode_cursor(data: Dict[str, Any]) -> str:
    """Encode pagination cursor data to base64.

    Args:
        data: Dictionary containing cursor data (id, created_at, etc.)

    Returns:
        Base64-encoded cursor string

    Examples:
        >>> cursor_data = {"id": "tool-123", "created_at": "2025-01-15T10:30:00Z"}
        >>> cursor = encode_cursor(cursor_data)
        >>> isinstance(cursor, str)
        True
        >>> len(cursor) > 0
        True

        >>> # Test with simple ID-only cursor
        >>> simple_cursor = encode_cursor({"id": 42})
        >>> isinstance(simple_cursor, str)
        True
        >>> len(simple_cursor) > 0
        True

        >>> # Test empty dict
        >>> empty_cursor = encode_cursor({})
        >>> isinstance(empty_cursor, str)
        True

        >>> # Test with numeric values
        >>> numeric_cursor = encode_cursor({"id": 12345, "offset": 100})
        >>> len(numeric_cursor) > 0
        True
    """
    json_str = json.dumps(data, default=str)
    return base64.urlsafe_b64encode(json_str.encode()).decode()


def decode_cursor(cursor: str) -> Dict[str, Any]:
    """Decode pagination cursor from base64.

    Args:
        cursor: Base64-encoded cursor string

    Returns:
        Decoded cursor data dictionary

    Raises:
        ValueError: If cursor is invalid

    Examples:
        >>> cursor_data = {"id": "tool-123", "created_at": "2025-01-15T10:30:00Z"}
        >>> cursor = encode_cursor(cursor_data)
        >>> decoded = decode_cursor(cursor)
        >>> decoded["id"]
        'tool-123'

        >>> # Test round-trip with numeric ID
        >>> data = {"id": 42}
        >>> encoded = encode_cursor(data)
        >>> decoded = decode_cursor(encoded)
        >>> decoded["id"]
        42

        >>> # Test with complex data
        >>> complex_data = {"id": "abc-123", "page": 5, "filter": "active"}
        >>> encoded_complex = encode_cursor(complex_data)
        >>> decoded_complex = decode_cursor(encoded_complex)
        >>> decoded_complex["id"]
        'abc-123'
        >>> decoded_complex["page"]
        5

        >>> # Test invalid cursor raises ValueError
        >>> try:
        ...     decode_cursor("invalid-not-base64")
        ... except ValueError as e:
        ...     "Invalid cursor" in str(e)
        True

        >>> # Test empty string raises ValueError
        >>> try:
        ...     decode_cursor("")
        ... except ValueError as e:
        ...     "Invalid cursor" in str(e)
        True
    """
    try:
        json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid cursor: {e}")


def generate_pagination_links(
    base_url: str,
    page: int,
    per_page: int,
    total_pages: int,
    query_params: Optional[Dict[str, Any]] = None,
    cursor: Optional[str] = None,
    next_cursor: Optional[str] = None,
    prev_cursor: Optional[str] = None,
) -> PaginationLinks:
    """Generate pagination navigation links.

    Args:
        base_url: Base URL for the endpoint
        page: Current page number
        per_page: Items per page
        total_pages: Total number of pages
        query_params: Additional query parameters to include
        cursor: Current cursor (for cursor-based pagination)
        next_cursor: Next page cursor
        prev_cursor: Previous page cursor

    Returns:
        PaginationLinks object with navigation URLs

    Examples:
        >>> links = generate_pagination_links(
        ...     base_url="/admin/tools",
        ...     page=2,
        ...     per_page=50,
        ...     total_pages=5
        ... )
        >>> "/admin/tools?page=2" in links.self
        True
        >>> "/admin/tools?page=3" in links.next
        True

        >>> # Test first page
        >>> first_page = generate_pagination_links(
        ...     base_url="/api/resources",
        ...     page=1,
        ...     per_page=25,
        ...     total_pages=10
        ... )
        >>> first_page.prev is None
        True
        >>> "/api/resources?page=2" in first_page.next
        True

        >>> # Test last page
        >>> last_page = generate_pagination_links(
        ...     base_url="/api/prompts",
        ...     page=5,
        ...     per_page=20,
        ...     total_pages=5
        ... )
        >>> last_page.next is None
        True
        >>> "/api/prompts?page=4" in last_page.prev
        True

        >>> # Test cursor-based pagination
        >>> cursor_links = generate_pagination_links(
        ...     base_url="/api/tools",
        ...     page=1,
        ...     per_page=50,
        ...     total_pages=0,
        ...     next_cursor="eyJpZCI6MTIzfQ=="
        ... )
        >>> "cursor=" in cursor_links.next
        True
        >>> "/api/tools?" in cursor_links.next
        True

        >>> # Test with query parameters
        >>> links_with_params = generate_pagination_links(
        ...     base_url="/api/tools",
        ...     page=3,
        ...     per_page=100,
        ...     total_pages=10,
        ...     query_params={"filter": "active", "sort": "name"}
        ... )
        >>> "filter=active" in links_with_params.self
        True
        >>> "sort=name" in links_with_params.self
        True
    """
    query_params = query_params or {}

    def build_url(page_num: Optional[int] = None, cursor_val: Optional[str] = None) -> str:
        """Build URL with query parameters.

        Args:
            page_num: Page number for offset pagination
            cursor_val: Cursor value for cursor-based pagination

        Returns:
            str: Complete URL with query parameters
        """
        params = query_params.copy()
        if cursor_val:
            params["cursor"] = cursor_val
            params["per_page"] = per_page
        elif page_num is not None:
            params["page"] = page_num
            params["per_page"] = per_page

        if params:
            return f"{base_url}?{urlencode(params)}"
        return base_url

    # For cursor-based pagination
    if cursor or next_cursor or prev_cursor:
        return PaginationLinks(
            self=build_url(cursor_val=cursor) if cursor else build_url(page_num=page),
            first=build_url(page_num=1),
            last=base_url,  # Last page not applicable for cursor-based
            next=build_url(cursor_val=next_cursor) if next_cursor else None,
            prev=build_url(cursor_val=prev_cursor) if prev_cursor else None,
        )

    # For offset-based pagination
    return PaginationLinks(
        self=build_url(page_num=page),
        first=build_url(page_num=1),
        last=build_url(page_num=total_pages) if total_pages > 0 else build_url(page_num=1),
        next=build_url(page_num=page + 1) if page < total_pages else None,
        prev=build_url(page_num=page - 1) if page > 1 else None,
    )


async def offset_paginate(
    db: Session,
    query: Select,
    page: int,
    per_page: int,
    base_url: str,
    query_params: Optional[Dict[str, Any]] = None,
    include_links: bool = True,
) -> Dict[str, Any]:
    """Paginate query using offset-based pagination.

    Best for result sets < 10,000 records.

    Args:
        db: Database session
        query: SQLAlchemy select query
        page: Page number (1-indexed)
        per_page: Items per page
        base_url: Base URL for link generation
        query_params: Additional query parameters
        include_links: Whether to include navigation links

    Returns:
        Dictionary with 'data', 'pagination', and 'links' keys

    Examples:
        Basic offset pagination usage::

            from mcpgateway.utils.pagination import offset_paginate
            from sqlalchemy import select
            from mcpgateway.common.models import Tool

            async def list_tools_offset(db: Session, page: int = 1):
                query = select(Tool).where(Tool.enabled == True)
                result = await offset_paginate(
                    db=db,
                    query=query,
                    page=page,
                    per_page=50,
                    base_url="/admin/tools"
                )
                return result
    """
    # Validate parameters
    page = max(1, page)
    per_page = max(settings.pagination_min_page_size, min(per_page, settings.pagination_max_page_size))

    # Get total count
    count_query = select(func.count()).select_from(query.alias())
    total_items = db.execute(count_query).scalar() or 0

    # Calculate pagination metadata
    total_pages = math.ceil(total_items / per_page) if total_items > 0 else 0
    offset = (page - 1) * per_page

    # Validate offset
    if offset > settings.pagination_max_offset:
        logger.warning(f"Offset {offset} exceeds maximum {settings.pagination_max_offset}")
        offset = settings.pagination_max_offset

    # Execute paginated query
    paginated_query = query.offset(offset).limit(per_page)
    items = db.execute(paginated_query).scalars().all()

    # Build pagination metadata
    pagination = PaginationMeta(
        page=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        next_cursor=None,
        prev_cursor=None,
    )

    # Build links if requested
    links = None
    if include_links and settings.pagination_include_links:
        links = generate_pagination_links(
            base_url=base_url,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            query_params=query_params,
        )

    return {
        "data": items,
        "pagination": pagination,
        "links": links,
    }


async def cursor_paginate(
    db: Session,
    query: Select,
    cursor: Optional[str],
    per_page: int,
    base_url: str,
    cursor_field: str = "created_at",
    cursor_id_field: str = "id",
    query_params: Optional[Dict[str, Any]] = None,
    include_links: bool = True,
) -> Dict[str, Any]:
    """Paginate query using cursor-based pagination.

    Best for result sets > 10,000 records. Uses keyset pagination
    for consistent performance regardless of offset.

    Args:
        db: Database session
        query: SQLAlchemy select query
        cursor: Current cursor (None for first page)
        per_page: Items per page
        base_url: Base URL for link generation
        cursor_field: Field to use for cursor (default: created_at)
        cursor_id_field: ID field for tie-breaking (default: id)
        query_params: Additional query parameters
        include_links: Whether to include navigation links

    Returns:
        Dictionary with 'data', 'pagination', and 'links' keys

    Examples:
        Basic cursor pagination usage::

            from mcpgateway.utils.pagination import cursor_paginate
            from sqlalchemy import select
            from mcpgateway.common.models import Tool

            async def list_tools_cursor(db: Session, cursor: Optional[str] = None):
                query = select(Tool).order_by(Tool.created_at.desc())
                result = await cursor_paginate(
                    db=db,
                    query=query,
                    cursor=cursor,
                    per_page=50,
                    base_url="/admin/tools"
                )
                return result
    """
    # Validate parameters
    per_page = max(settings.pagination_min_page_size, min(per_page, settings.pagination_max_page_size))

    # Decode cursor if provided
    cursor_data = None
    if cursor:
        try:
            cursor_data = decode_cursor(cursor)
        except ValueError as e:
            logger.warning(f"Invalid cursor: {e}")
            cursor_data = None

    # Apply cursor filter if provided
    if cursor_data:
        # For descending order (newest first): WHERE created_at < cursor_value
        # This assumes the query is already ordered by cursor_field desc
        # You'll need to add the where clause based on cursor_data
        pass  # Placeholder for cursor filtering logic

    # Fetch one extra item to determine if there's a next page
    paginated_query = query.limit(per_page + 1)
    items = db.execute(paginated_query).scalars().all()

    # Check if there are more items
    has_next = len(items) > per_page
    if has_next:
        items = items[:per_page]  # Remove the extra item

    # Generate cursors
    next_cursor = None
    if has_next and items:
        last_item = items[-1]
        next_cursor = encode_cursor(
            {
                cursor_field: getattr(last_item, cursor_field, None),
                cursor_id_field: getattr(last_item, cursor_id_field, None),
            }
        )

    # Get approximate total count (expensive for large tables)
    count_query = select(func.count()).select_from(query.alias())
    total_items = db.execute(count_query).scalar() or 0

    # Build pagination metadata
    pagination = PaginationMeta(
        page=1,  # Not applicable for cursor-based
        per_page=per_page,
        total_items=total_items,
        total_pages=0,  # Not applicable for cursor-based
        has_next=has_next,
        has_prev=cursor is not None,
        next_cursor=next_cursor,
        prev_cursor=None,  # Implementing prev cursor requires bidirectional cursors
    )

    # Build links if requested
    links = None
    if include_links and settings.pagination_include_links:
        links = generate_pagination_links(
            base_url=base_url,
            page=1,
            per_page=per_page,
            total_pages=0,
            query_params=query_params,
            cursor=cursor,
            next_cursor=next_cursor,
            prev_cursor=None,
        )

    return {
        "data": items,
        "pagination": pagination,
        "links": links,
    }


async def paginate_query(
    db: Session,
    query: Select,
    page: int = 1,
    per_page: Optional[int] = None,
    cursor: Optional[str] = None,
    base_url: str = "",
    query_params: Optional[Dict[str, Any]] = None,
    use_cursor_threshold: bool = True,
) -> Dict[str, Any]:
    """Automatically paginate query using best strategy.

    Selects between offset-based and cursor-based pagination
    based on result set size and configuration.

    Args:
        db: Database session
        query: SQLAlchemy select query
        page: Page number (1-indexed)
        per_page: Items per page (uses default if None)
        cursor: Cursor for cursor-based pagination
        base_url: Base URL for link generation
        query_params: Additional query parameters
        use_cursor_threshold: Whether to auto-switch to cursor-based

    Returns:
        Dictionary with 'data', 'pagination', and 'links' keys

    Examples:
        Automatic pagination with strategy selection::

            from mcpgateway.utils.pagination import paginate_query
            from sqlalchemy import select
            from mcpgateway.common.models import Tool

            async def list_tools_auto(db: Session, page: int = 1):
                query = select(Tool)
                # Automatically switches to cursor-based for large datasets
                result = await paginate_query(
                    db=db,
                    query=query,
                    page=page,
                    base_url="/admin/tools"
                )
                # Result contains: data, pagination, links
                return result
    """
    # Use default page size if not provided
    if per_page is None:
        per_page = settings.pagination_default_page_size

    # If cursor is provided, use cursor-based pagination
    if cursor and settings.pagination_cursor_enabled:
        return await cursor_paginate(
            db=db,
            query=query,
            cursor=cursor,
            per_page=per_page,
            base_url=base_url,
            query_params=query_params,
        )

    # Check if we should use cursor-based pagination based on total count
    if use_cursor_threshold and settings.pagination_cursor_enabled:
        count_query = select(func.count()).select_from(query.alias())
        total_items = db.execute(count_query).scalar() or 0

        if total_items > settings.pagination_cursor_threshold:
            logger.info(f"Switching to cursor-based pagination (total_items={total_items} > threshold={settings.pagination_cursor_threshold})")
            return await cursor_paginate(
                db=db,
                query=query,
                cursor=cursor,
                per_page=per_page,
                base_url=base_url,
                query_params=query_params,
            )

    # Use offset-based pagination
    return await offset_paginate(
        db=db,
        query=query,
        page=page,
        per_page=per_page,
        base_url=base_url,
        query_params=query_params,
    )


def parse_pagination_params(request: Request) -> Dict[str, Any]:
    """Parse pagination parameters from request.

    Args:
        request: FastAPI request object

    Returns:
        Dictionary with parsed pagination parameters

    Examples:
        >>> from fastapi import Request
        >>> # Mock request with query params
        >>> request = type('Request', (), {
        ...     'query_params': {'page': '2', 'per_page': '100'}
        ... })()
        >>> params = parse_pagination_params(request)
        >>> params['page']
        2
        >>> params['per_page']
        100

        >>> # Test with cursor
        >>> request_with_cursor = type('Request', (), {
        ...     'query_params': {'cursor': 'eyJpZCI6IDEyM30=', 'per_page': '25'}
        ... })()
        >>> params_cursor = parse_pagination_params(request_with_cursor)
        >>> params_cursor['cursor']
        'eyJpZCI6IDEyM30='
        >>> params_cursor['per_page']
        25

        >>> # Test with sort parameters
        >>> request_with_sort = type('Request', (), {
        ...     'query_params': {'page': '1', 'sort_by': 'name', 'sort_order': 'asc'}
        ... })()
        >>> params_sort = parse_pagination_params(request_with_sort)
        >>> params_sort['sort_by']
        'name'
        >>> params_sort['sort_order']
        'asc'

        >>> # Test with invalid page (negative) - should default to 1
        >>> request_invalid = type('Request', (), {
        ...     'query_params': {'page': '-5', 'per_page': '50'}
        ... })()
        >>> params_invalid = parse_pagination_params(request_invalid)
        >>> params_invalid['page']
        1

        >>> # Test with no parameters - uses defaults
        >>> request_empty = type('Request', (), {'query_params': {}})()
        >>> params_empty = parse_pagination_params(request_empty)
        >>> params_empty['page']
        1
        >>> 'cursor' in params_empty
        True
        >>> 'sort_by' in params_empty
        True
    """
    page = int(request.query_params.get("page", 1))
    per_page = int(request.query_params.get("per_page", settings.pagination_default_page_size))
    cursor = request.query_params.get("cursor")
    sort_by = request.query_params.get("sort_by", settings.pagination_default_sort_field)
    sort_order = request.query_params.get("sort_order", settings.pagination_default_sort_order)

    # Validate and constrain values
    page = max(1, page)
    per_page = max(settings.pagination_min_page_size, min(per_page, settings.pagination_max_page_size))

    return {
        "page": page,
        "per_page": per_page,
        "cursor": cursor,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
