# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_pagination.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit Tests for Pagination Utilities.

This module tests pagination functionality including:
- Cursor encoding/decoding
- Pagination link generation
- Offset-based pagination
- Cursor-based pagination
- Query parameter parsing
"""

# Standard
import base64
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest
from fastapi import Request
from sqlalchemy import desc, select

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Tool
from mcpgateway.schemas import PaginationLinks, PaginationMeta
from mcpgateway.utils.pagination import (
    cursor_paginate,
    decode_cursor,
    encode_cursor,
    generate_pagination_links,
    offset_paginate,
    paginate_query,
    parse_pagination_params,
    unified_paginate,
)


class TestCursorEncoding:
    """Test cursor encoding and decoding functions."""

    def test_encode_cursor_basic(self):
        """Test basic cursor encoding."""
        data = {"id": "tool-123", "created_at": "2025-01-15T10:30:00Z"}
        cursor = encode_cursor(data)

        assert isinstance(cursor, str)
        assert len(cursor) > 0

        # Verify it's valid base64
        decoded_bytes = base64.urlsafe_b64decode(cursor)
        decoded_data = json.loads(decoded_bytes.decode())
        assert decoded_data == data

    def test_encode_cursor_with_datetime(self):
        """Test cursor encoding with datetime objects."""
        now = datetime.now(timezone.utc)
        data = {"id": "tool-456", "created_at": now}
        cursor = encode_cursor(data)

        assert isinstance(cursor, str)
        # Datetime should be serialized as string
        decoded_data = decode_cursor(cursor)
        assert decoded_data["id"] == "tool-456"
        assert "created_at" in decoded_data

    def test_decode_cursor_valid(self):
        """Test decoding a valid cursor."""
        original_data = {"id": "tool-789", "created_at": "2025-01-15T10:30:00Z", "page": 2}
        cursor = encode_cursor(original_data)

        decoded_data = decode_cursor(cursor)
        assert decoded_data == original_data

    def test_decode_cursor_invalid_base64(self):
        """Test decoding an invalid base64 cursor."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor("not-valid-base64!!!")

    def test_decode_cursor_invalid_json(self):
        """Test decoding cursor with invalid JSON."""
        invalid_json = base64.urlsafe_b64encode(b"not json").decode()
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(invalid_json)

    def test_encode_decode_round_trip(self):
        """Test encoding and decoding round trip."""
        test_data = {
            "id": "tool-999",
            "created_at": "2025-01-15T10:30:00Z",
            "team_id": "team-abc",
            "page": 5,
        }

        cursor = encode_cursor(test_data)
        decoded = decode_cursor(cursor)

        assert decoded == test_data


class TestPaginationLinks:
    """Test pagination link generation."""

    def test_generate_links_first_page(self):
        """Test link generation for first page."""
        links = generate_pagination_links(
            base_url="/admin/tools",
            page=1,
            per_page=50,
            total_pages=10,
        )

        assert isinstance(links, PaginationLinks)
        assert "/admin/tools?page=1" in links.self
        assert "/admin/tools?page=1" in links.first
        assert "/admin/tools?page=10" in links.last
        assert "/admin/tools?page=2" in links.next
        assert links.prev is None

    def test_generate_links_middle_page(self):
        """Test link generation for middle page."""
        links = generate_pagination_links(
            base_url="/admin/tools",
            page=5,
            per_page=50,
            total_pages=10,
        )

        assert "/admin/tools?page=5" in links.self
        assert "/admin/tools?page=6" in links.next
        assert "/admin/tools?page=4" in links.prev

    def test_generate_links_last_page(self):
        """Test link generation for last page."""
        links = generate_pagination_links(
            base_url="/admin/tools",
            page=10,
            per_page=50,
            total_pages=10,
        )

        assert "/admin/tools?page=10" in links.self
        assert links.next is None
        assert "/admin/tools?page=9" in links.prev

    def test_generate_links_with_query_params(self):
        """Test link generation with additional query parameters."""
        links = generate_pagination_links(
            base_url="/admin/tools",
            page=2,
            per_page=50,
            total_pages=5,
            query_params={"include_inactive": True, "team_id": "team-123"},
        )

        assert "include_inactive=True" in links.self
        assert "team_id=team-123" in links.self
        assert "page=2" in links.self

    def test_generate_links_single_page(self):
        """Test link generation for single page result."""
        links = generate_pagination_links(
            base_url="/admin/tools",
            page=1,
            per_page=50,
            total_pages=1,
        )

        assert links.next is None
        assert links.prev is None
        assert "/admin/tools?page=1" in links.last

    def test_generate_links_cursor_based(self):
        """Test link generation for cursor-based pagination."""
        cursor = encode_cursor({"id": "tool-123", "created_at": "2025-01-15T10:30:00Z"})
        next_cursor = encode_cursor({"id": "tool-173", "created_at": "2025-01-15T09:00:00Z"})

        links = generate_pagination_links(
            base_url="/admin/tools",
            page=1,
            per_page=50,
            total_pages=0,
            cursor=cursor,
            next_cursor=next_cursor,
        )

        # The cursor will be URL-encoded, so check for the decoded value
        from urllib.parse import unquote

        assert cursor in unquote(links.self)
        assert next_cursor in unquote(links.next)
        assert links.prev is None

    def test_generate_links_cursor_based_self_without_page_params(self):
        """Cursor mode shouldn't require offset params when no page is provided."""
        next_cursor = "next-cursor"

        links = generate_pagination_links(
            base_url="/admin/tools",
            page=None,  # Cursor mode may be invoked by next_cursor without an offset page number.
            per_page=50,
            total_pages=0,
            next_cursor=next_cursor,
        )

        assert links.self == "/admin/tools"


class TestOffsetPagination:
    """Test offset-based pagination."""

    @pytest.mark.asyncio
    async def test_offset_paginate_first_page(self, db_session):
        """Test offset pagination for first page."""
        # Create mock tools
        for i in range(100):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},  # Add valid JSON schema
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        result = await offset_paginate(
            db=db_session,
            query=query,
            page=1,
            per_page=20,
            base_url="/admin/tools",
        )

        assert len(result["data"]) == 20
        pagination = result["pagination"]
        assert pagination.page == 1
        assert pagination.per_page == 20
        assert pagination.total_items == 100
        assert pagination.total_pages == 5
        assert pagination.has_next is True
        assert pagination.has_prev is False

    @pytest.mark.asyncio
    async def test_offset_paginate_middle_page(self, db_session):
        """Test offset pagination for middle page."""
        for i in range(100):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        result = await offset_paginate(
            db=db_session,
            query=query,
            page=3,
            per_page=20,
            base_url="/admin/tools",
        )

        assert len(result["data"]) == 20
        pagination = result["pagination"]
        assert pagination.page == 3
        assert pagination.has_next is True
        assert pagination.has_prev is True

    @pytest.mark.asyncio
    async def test_offset_paginate_last_page(self, db_session):
        """Test offset pagination for last page."""
        for i in range(95):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        result = await offset_paginate(
            db=db_session,
            query=query,
            page=5,
            per_page=20,
            base_url="/admin/tools",
        )

        # Last page should have 15 items (95 % 20)
        assert len(result["data"]) == 15
        pagination = result["pagination"]
        assert pagination.page == 5
        assert pagination.has_next is False
        assert pagination.has_prev is True

    @pytest.mark.asyncio
    async def test_offset_paginate_empty_result(self, db_session):
        """Test offset pagination with no results."""
        query = select(Tool).where(Tool.enabled.is_(True))

        result = await offset_paginate(
            db=db_session,
            query=query,
            page=1,
            per_page=20,
            base_url="/admin/tools",
        )

        assert len(result["data"]) == 0
        pagination = result["pagination"]
        assert pagination.total_items == 0
        assert pagination.total_pages == 0

    @pytest.mark.asyncio
    async def test_offset_paginate_parameter_validation(self, db_session):
        """Test pagination parameter validation."""
        query = select(Tool)

        # Test negative page number
        result = await offset_paginate(
            db=db_session,
            query=query,
            page=-5,
            per_page=20,
            base_url="/admin/tools",
        )
        pagination = result["pagination"]
        assert pagination.page == 1

        # Test page size exceeds maximum
        result = await offset_paginate(
            db=db_session,
            query=query,
            page=1,
            per_page=10000,  # Exceeds max
            base_url="/admin/tools",
        )
        pagination = result["pagination"]
        assert pagination.per_page == settings.pagination_max_page_size

    @pytest.mark.asyncio
    async def test_offset_paginate_without_links(self, db_session):
        """Test offset pagination without generating links."""
        for i in range(50):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        result = await offset_paginate(
            db=db_session,
            query=query,
            page=1,
            per_page=20,
            base_url="/admin/tools",
            include_links=False,
        )

        assert result["links"] is None
        assert "pagination" in result

    @pytest.mark.asyncio
    async def test_offset_paginate_clamps_offset_to_max(self, db_session, monkeypatch, caplog):
        """When page would produce an offset larger than pagination_max_offset, clamp it."""
        for i in range(30):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        monkeypatch.setattr(settings, "pagination_max_offset", 5)

        query = select(Tool).where(Tool.enabled.is_(True))
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.pagination"):
            result = await offset_paginate(
                db=db_session,
                query=query,
                page=100,
                per_page=10,
                base_url="/admin/tools",
            )

        assert len(result["data"]) == 10
        assert any("exceeds maximum" in record.message for record in caplog.records)


class TestCursorPagination:
    """Test cursor-based pagination."""

    @pytest.mark.asyncio
    async def test_cursor_paginate_first_page(self, db_session):
        """Test cursor pagination for first page."""
        for i in range(100):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))

        result = await cursor_paginate(
            db=db_session,
            query=query,
            cursor=None,
            per_page=20,
            base_url="/admin/tools",
        )

        assert len(result["data"]) == 20
        pagination = result["pagination"]
        assert pagination.has_next is True
        assert pagination.next_cursor is not None

    @pytest.mark.asyncio
    async def test_cursor_paginate_with_cursor(self, db_session):
        """Test cursor pagination with a cursor."""
        for i in range(100):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        # First page to get a cursor
        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))
        first_page = await cursor_paginate(
            db=db_session,
            query=query,
            cursor=None,
            per_page=20,
            base_url="/admin/tools",
        )

        next_cursor = first_page["pagination"].next_cursor
        assert next_cursor is not None

        # Second page using cursor
        second_page = await cursor_paginate(
            db=db_session,
            query=query,
            cursor=next_cursor,
            per_page=20,
            base_url="/admin/tools",
        )

        assert len(second_page["data"]) == 20
        pagination = second_page["pagination"]
        assert pagination.has_prev is True

    @pytest.mark.asyncio
    async def test_cursor_paginate_invalid_cursor(self, db_session):
        """Test cursor pagination with invalid cursor."""
        query = select(Tool).where(Tool.enabled.is_(True))

        # Invalid cursor should be handled gracefully
        result = await cursor_paginate(
            db=db_session,
            query=query,
            cursor="invalid-cursor-data",
            per_page=20,
            base_url="/admin/tools",
        )

        # Should fall back to first page
        assert "data" in result
        assert "pagination" in result

    @pytest.mark.asyncio
    async def test_cursor_paginate_cursor_missing_id_skips_filter(self):
        """Cursor missing id should not apply the keyset filter and should not crash."""
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        item1 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0002")
        item2 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0001")

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [item1, item2]

        cursor = encode_cursor({"created_at": datetime.now(timezone.utc).isoformat()})
        result = await cursor_paginate(
            db=mock_db,
            query=mock_query,
            cursor=cursor,
            per_page=1,
            base_url="/admin/tools",
            include_links=False,
            total_count=2,
        )

        assert result["pagination"].has_prev is True

    @pytest.mark.asyncio
    async def test_cursor_paginate_cursor_value_not_str_skips_datetime_parse(self):
        """Cursor with non-string created_at should skip datetime parsing."""
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        item1 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0002")
        item2 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0001")

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [item1, item2]

        cursor = encode_cursor({"created_at": 123, "id": "tool-9999"})
        result = await cursor_paginate(
            db=mock_db,
            query=mock_query,
            cursor=cursor,
            per_page=1,
            base_url="/admin/tools",
            include_links=False,
            total_count=2,
        )

        assert result["pagination"].has_prev is True

    @pytest.mark.asyncio
    async def test_cursor_paginate_without_links(self, db_session):
        """Test cursor pagination skips link generation when include_links=False."""
        for i in range(10):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.id))
        result = await cursor_paginate(db=db_session, query=query, cursor=None, per_page=5, base_url="/admin/tools", include_links=False)
        assert result["links"] is None

    @pytest.mark.asyncio
    async def test_cursor_paginate_cursor_parse_failure_and_no_entities(self):
        """Cover cursor datetime parse failure and the branch where query.column_descriptions is empty."""
        # The implementation tries to parse cursor_value with datetime.fromisoformat;
        # provide a non-ISO string and a query with no entities so no WHERE clause is applied.
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        item1 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0002")
        item2 = SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0001")

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [item1, item2]

        bad_cursor = encode_cursor({"id": "tool-0009", "created_at": "not-a-datetime"})
        result = await cursor_paginate(
            db=mock_db,
            query=mock_query,
            cursor=bad_cursor,
            per_page=1,
            base_url="/admin/tools",
            include_links=False,
            total_count=2,
        )

        assert result["pagination"].has_next is True
        assert result["pagination"].next_cursor is not None


class TestPaginateQuery:
    """Test automatic pagination strategy selection."""

    @pytest.mark.asyncio
    async def test_paginate_query_offset_default(self, db_session):
        """Test that offset pagination is used by default for small datasets."""
        for i in range(100):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        result = await paginate_query(
            db=db_session,
            query=query,
            page=1,
            base_url="/admin/tools",
        )

        assert "pagination" in result
        pagination = result["pagination"]
        assert pagination.page == 1

    @pytest.mark.asyncio
    async def test_paginate_query_with_cursor(self, db_session):
        """Test that cursor is used when explicitly provided."""
        for i in range(50):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))
        cursor = encode_cursor({"id": "tool-10", "created_at": "2025-01-15T10:30:00Z"})

        result = await paginate_query(
            db=db_session,
            query=query,
            cursor=cursor,
            base_url="/admin/tools",
        )

        assert "pagination" in result
        # Cursor-based pagination doesn't use page numbers
        pagination = result["pagination"]
        assert pagination.page == 1

    @pytest.mark.asyncio
    async def test_paginate_query_switches_to_cursor_based_when_above_threshold(self, db_session, monkeypatch, caplog):
        monkeypatch.setattr(settings, "pagination_cursor_enabled", True)
        monkeypatch.setattr(settings, "pagination_cursor_threshold", 10)

        for i in range(25):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))

        with caplog.at_level(logging.INFO, logger="mcpgateway.utils.pagination"):
            result = await paginate_query(db=db_session, query=query, page=1, per_page=5, base_url="/admin/tools")

        # Cursor-based PaginationMeta uses total_pages=0 and cursor fields.
        assert result["pagination"].total_pages == 0
        assert result["pagination"].next_cursor is not None
        assert any("Switching to cursor-based pagination" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_paginate_query_uses_provided_total_count(self, monkeypatch, db_session):
        monkeypatch.setattr(settings, "pagination_cursor_enabled", True)
        monkeypatch.setattr(settings, "pagination_cursor_threshold", 1)

        for i in range(3):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))
        result = await paginate_query(db=db_session, query=query, page=1, per_page=2, base_url="/admin/tools", total_count=999)

        assert result["pagination"].total_items == 999

    @pytest.mark.asyncio
    async def test_paginate_query_use_cursor_threshold_false_forces_offset(self, db_session):
        for i in range(5):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))
        result = await paginate_query(
            db=db_session,
            query=query,
            page=1,
            per_page=2,  # Explicitly provided to cover the "per_page is not None" branch.
            base_url="/admin/tools",
            use_cursor_threshold=False,
        )

        assert result["pagination"].total_pages > 0


class TestUnifiedPaginate:
    """Tests for unified_paginate helper."""

    @pytest.mark.asyncio
    async def test_unified_paginate_page_mode_delegates_to_paginate_query(self, monkeypatch):
        import mcpgateway.utils.pagination as pagination_mod

        called: dict[str, object] = {}

        async def fake_paginate_query(**kwargs):  # noqa: ANN003
            called.update(kwargs)
            return {"data": ["x"], "pagination": {"page": 1}, "links": None}

        monkeypatch.setattr(pagination_mod, "paginate_query", fake_paginate_query)

        res = await unified_paginate(
            db=MagicMock(),
            query=MagicMock(),
            page=1,
            per_page=None,
            limit=7,  # Used as default per_page when per_page is None
            base_url="/admin/tools",
            query_params={"q": "x"},
        )

        assert res["data"] == ["x"]
        assert called["use_cursor_threshold"] is False
        assert called["per_page"] == 7

    @pytest.mark.asyncio
    async def test_unified_paginate_page_mode_respects_explicit_per_page(self, monkeypatch):
        import mcpgateway.utils.pagination as pagination_mod

        called: dict[str, object] = {}

        async def fake_paginate_query(**kwargs):  # noqa: ANN003
            called.update(kwargs)
            return {"data": ["x"], "pagination": {"page": 1}, "links": None}

        monkeypatch.setattr(pagination_mod, "paginate_query", fake_paginate_query)

        res = await unified_paginate(
            db=MagicMock(),
            query=MagicMock(),
            page=1,
            per_page=3,
            limit=7,  # Should be ignored when per_page is explicit
            base_url="/admin/tools",
        )

        assert res["data"] == ["x"]
        assert called["per_page"] == 3

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_mode_limit_zero_fetches_all(self, db_session):
        for i in range(12):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))
        items, next_cursor = await unified_paginate(db=db_session, query=query, limit=0)

        assert len(items) == 12
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_mode_default_page_size_when_limit_none(self, db_session):
        for i in range(3):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))
        items, next_cursor = await unified_paginate(db=db_session, query=query, limit=None)

        assert len(items) == 3
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_mode_generates_next_cursor(self, db_session):
        for i in range(12):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))
        items, next_cursor = await unified_paginate(db=db_session, query=query, limit=5)

        assert len(items) == 5
        assert next_cursor is not None

        decoded = decode_cursor(next_cursor)
        assert "created_at" in decoded
        assert "id" in decoded

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_mode_uses_cursor_for_next_page(self, db_session):
        for i in range(12):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))
        page1_items, cursor1 = await unified_paginate(db=db_session, query=query, limit=5)
        assert cursor1 is not None

        page2_items, _cursor2 = await unified_paginate(db=db_session, query=query, limit=5, cursor=cursor1)

        page1_ids = {t.id for t in page1_items}
        page2_ids = {t.id for t in page2_items}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_unified_paginate_invalid_cursor_is_ignored(self, db_session, caplog):
        for i in range(10):
            tool = Tool(
                id=f"tool-{i:04d}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True)).order_by(desc(Tool.created_at), desc(Tool.id))

        bad_cursor = encode_cursor({"id": "tool-0000", "created_at": "not-a-date"})
        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.pagination"):
            items, next_cursor = await unified_paginate(db=db_session, query=query, limit=5, cursor=bad_cursor)

        assert len(items) == 5
        assert any("Invalid cursor, ignoring" in record.message for record in caplog.records)
        assert next_cursor is not None

    @pytest.mark.asyncio
    async def test_unified_paginate_warns_when_items_lack_id_field(self, caplog):
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(created_at=datetime.now(timezone.utc)),
            SimpleNamespace(created_at=datetime.now(timezone.utc)),
        ]

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.pagination"):
            items, next_cursor = await unified_paginate(db=mock_db, query=mock_query, limit=1)

        assert len(items) == 1
        assert next_cursor is not None
        assert any("has no 'id' field" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_missing_created_at_in_cursor_is_ignored(self):
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0002"),
            SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0001"),
        ]

        cursor = encode_cursor({"id": "tool-9999"})  # created_at omitted
        items, next_cursor = await unified_paginate(db=mock_db, query=mock_query, limit=1, cursor=cursor)

        assert len(items) == 1
        assert next_cursor is not None

    @pytest.mark.asyncio
    async def test_unified_paginate_cursor_entities_empty_skips_filter(self):
        mock_query = MagicMock()
        mock_query.column_descriptions = []  # Forces the entities=False branch
        mock_query.limit.return_value = mock_query

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0002"),
            SimpleNamespace(created_at=datetime.now(timezone.utc), id="tool-0001"),
        ]

        cursor = encode_cursor({"id": "tool-9999", "created_at": datetime.now(timezone.utc).isoformat()})
        items, next_cursor = await unified_paginate(db=mock_db, query=mock_query, limit=1, cursor=cursor)

        assert len(items) == 1
        assert next_cursor is not None

    @pytest.mark.asyncio
    async def test_unified_paginate_next_cursor_skips_datetime_serialization_when_missing(self):
        mock_query = MagicMock()
        mock_query.column_descriptions = []
        mock_query.limit.return_value = mock_query

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            SimpleNamespace(created_at=None, id="tool-0002"),
            SimpleNamespace(created_at=None, id="tool-0001"),
        ]

        items, next_cursor = await unified_paginate(db=mock_db, query=mock_query, limit=1)

        assert len(items) == 1
        assert next_cursor is not None
        decoded = decode_cursor(next_cursor)
        assert decoded["created_at"] is None


class TestParsePaginationParams:
    """Test pagination parameter parsing from requests."""

    def test_parse_default_params(self):
        """Test parsing with default parameters."""
        mock_request = MagicMock(spec=Request)
        mock_request.query_params = {}

        params = parse_pagination_params(mock_request)

        assert params["page"] == 1
        assert params["per_page"] == settings.pagination_default_page_size
        assert params["cursor"] is None

    def test_parse_custom_params(self):
        """Test parsing with custom parameters."""
        mock_request = MagicMock(spec=Request)
        mock_request.query_params = {
            "page": "5",
            "per_page": "100",
            "cursor": "abc123",
            "sort_by": "name",
            "sort_order": "asc",
        }

        params = parse_pagination_params(mock_request)

        assert params["page"] == 5
        assert params["per_page"] == 100
        assert params["cursor"] == "abc123"
        assert params["sort_by"] == "name"
        assert params["sort_order"] == "asc"

    def test_parse_invalid_page_number(self):
        """Test parsing with invalid page number."""
        mock_request = MagicMock(spec=Request)
        mock_request.query_params = {"page": "0"}

        params = parse_pagination_params(mock_request)

        # Should be constrained to minimum 1
        assert params["page"] == 1

    def test_parse_excessive_page_size(self):
        """Test parsing with excessive page size."""
        mock_request = MagicMock(spec=Request)
        mock_request.query_params = {"per_page": "10000"}

        params = parse_pagination_params(mock_request)

        # Should be constrained to maximum
        assert params["per_page"] == settings.pagination_max_page_size

    def test_parse_minimal_page_size(self):
        """Test parsing with minimal page size."""
        mock_request = MagicMock(spec=Request)
        mock_request.query_params = {"per_page": "0"}

        params = parse_pagination_params(mock_request)

        # Should be constrained to minimum
        assert params["per_page"] == settings.pagination_min_page_size


class TestPaginationSchemas:
    """Test pagination schema models."""

    def test_pagination_meta_creation(self):
        """Test PaginationMeta model creation."""
        meta = PaginationMeta(
            page=2,
            per_page=50,
            total_items=250,
            total_pages=5,
            has_next=True,
            has_prev=True,
            next_cursor=None,
            prev_cursor=None,
        )

        assert meta.page == 2
        assert meta.total_items == 250
        assert meta.has_next is True

    def test_pagination_links_creation(self):
        """Test PaginationLinks model creation."""
        links = PaginationLinks(
            self="/admin/tools?page=2",
            first="/admin/tools?page=1",
            last="/admin/tools?page=10",
            next="/admin/tools?page=3",
            prev="/admin/tools?page=1",
        )

        assert links.self == "/admin/tools?page=2"
        assert links.next == "/admin/tools?page=3"
        assert links.prev == "/admin/tools?page=1"

    def test_pagination_links_optional_fields(self):
        """Test PaginationLinks with optional fields."""
        links = PaginationLinks(
            self="/admin/tools?page=1",
            first="/admin/tools?page=1",
            last="/admin/tools?page=1",
            next=None,  # No next page
            prev=None,  # No previous page
        )

        assert links.next is None
        assert links.prev is None


class TestTotalCountOptimization:
    """Test that pre-computed total_count avoids duplicate COUNT queries."""

    @pytest.mark.asyncio
    async def test_offset_paginate_uses_precomputed_count(self, db_session):
        """Test that offset_paginate uses total_count when provided."""
        for i in range(50):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        # Pass a pre-computed count (intentionally wrong to verify it's used)
        result = await offset_paginate(
            db=db_session,
            query=query,
            page=1,
            per_page=20,
            base_url="/admin/tools",
            total_count=999,  # Fake count to verify it's used
        )

        # Should use the provided count, not query the database
        pagination = result["pagination"]
        assert pagination.total_items == 999
        assert pagination.total_pages == 50  # ceil(999/20)

    @pytest.mark.asyncio
    async def test_cursor_paginate_uses_precomputed_count(self, db_session):
        """Test that cursor_paginate uses total_count when provided."""
        for i in range(50):
            tool = Tool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
            )
            db_session.add(tool)
        db_session.commit()

        query = select(Tool).where(Tool.enabled.is_(True))

        # Pass a pre-computed count (intentionally wrong to verify it's used)
        result = await cursor_paginate(
            db=db_session,
            query=query,
            cursor=None,
            per_page=20,
            base_url="/admin/tools",
            total_count=888,  # Fake count to verify it's used
        )

        # Should use the provided count, not query the database
        pagination = result["pagination"]
        assert pagination.total_items == 888


# Pytest fixtures


@pytest.fixture
def db_session():
    """Create a test database session."""
    # Standard

    # Third-Party
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # First-Party
    from mcpgateway.db import Base

    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # Create session
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()  # Properly close all connections in the pool
