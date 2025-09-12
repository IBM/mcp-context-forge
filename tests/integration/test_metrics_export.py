# -*- coding: utf-8 -*-
"""
Integration tests for metrics export endpoints.
"""

# Standard
import csv
from io import StringIO
from typing import Dict, List, Any

# Third-party
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# First-party
from mcpgateway.db import get_db, Tool as DbTool, ToolMetric
from mcpgateway.main import app
from mcpgateway.utils.metrics_common import format_response_time

# Tests
from tests.conftest import MockAuthMiddleware


@pytest.fixture
def mock_db_with_metrics(db_session):
    """Create a database session with tool metrics for testing."""
    # Create test tools
    tools = []
    for i in range(10):  # Create 10 tools to ensure we test beyond the default limit of 5
        tool = DbTool(
            name=f"test_tool_{i}",
            url=f"http://example.com/tool_{i}",
            integration_type="REST",
            enabled=True
        )
        db_session.add(tool)
        tools.append(tool)
    db_session.commit()
    
    # Add metrics for each tool
    import datetime
    from datetime import timedelta
    
    now = datetime.datetime.now(datetime.timezone.utc)
    
    for i, tool in enumerate(tools):
        # Add successful metrics
        successful_count = i + 1
        # Add different numbers of metrics to each tool to test sorting
        for j in range(successful_count):
            metric = ToolMetric(
                tool_id=tool.id,
                is_success=True,
                response_time=1.0 + (j * 0.1),  # Different response times
                timestamp=now - timedelta(minutes=j)
            )
            db_session.add(metric)
        
        # Add failed metrics for some tools to test success rate
        if i % 2 == 0:  # Even numbered tools have some failures
            failed_count = i // 2
            for j in range(failed_count):
                metric = ToolMetric(
                    tool_id=tool.id,
                    is_success=False,
                    response_time=2.0 + (j * 0.1),  # Different response times
                    timestamp=now - timedelta(minutes=j + successful_count)
                )
                db_session.add(metric)
    
    db_session.commit()
    return db_session


@pytest.mark.asyncio
async def test_export_metrics_csv(mock_db_with_metrics):
    """Test exporting metrics to CSV format."""
    # Override the get_db dependency
    app.dependency_overrides[get_db] = lambda: mock_db_with_metrics
    
    # Apply auth middleware for testing
    app.middleware_stack = MockAuthMiddleware(app)
    
    # Create test client
    client = TestClient(app)
    
    # Test export for tools
    response = client.get("/admin/metrics/export?entity_type=tools")
    
    # Check response status and headers
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv"
    assert "attachment; filename=tools_metrics.csv" in response.headers["Content-Disposition"]
    
    # Parse CSV content
    content = response.content.decode("utf-8")
    reader = csv.reader(StringIO(content))
    rows = list(reader)
    
    # Check headers
    headers = rows[0]
    assert headers == ["ID", "Name", "Execution Count", "Average Response Time (s)", "Success Rate (%)", "Last Execution"]
    
    # Check data rows
    data_rows = rows[1:]
    
    # Should export all rows, not just top 5
    assert len(data_rows) > 5
    
    # Check first row (should be the tool with highest execution count)
    tool_data = data_rows[0]
    assert tool_data[1].startswith("test_tool_")  # Name
    assert int(tool_data[2]) > 0  # Execution Count
    
    # Verify response time format (x.xxx)
    for row in data_rows:
        if row[3] != "N/A":
            assert len(row[3].split(".")[-1]) == 3  # 3 decimal places
    
    # Test with explicit limit
    limited_response = client.get("/admin/metrics/export?entity_type=tools&limit=3")
    limited_content = limited_response.content.decode("utf-8")
    limited_reader = csv.reader(StringIO(limited_content))
    limited_rows = list(limited_reader)
    assert len(limited_rows) == 4  # header + 3 data rows
    
    # Test with no data
    # First clear the metrics
    mock_db_with_metrics.query(ToolMetric).delete()
    mock_db_with_metrics.commit()
    
    empty_response = client.get("/admin/metrics/export?entity_type=tools")
    empty_content = empty_response.content.decode("utf-8")
    empty_reader = csv.reader(StringIO(empty_content))
    empty_rows = list(empty_reader)
    assert len(empty_rows) == 1  # just header
    
    # Clean up
    app.dependency_overrides.clear()
