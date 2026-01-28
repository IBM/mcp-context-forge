# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/utils/db_util.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Main module for handling toolops related database operations.

This module defines the utility funtions to read/write/update toolops related database tables.
"""
# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import Tool
from mcpgateway.db import ToolOpsTestCases as TestCaseRecord
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.services_auth import decode_auth

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def populate_testcases_table(tool_id, test_cases, run_status, db: Session):
    """
    Method to write and update toolops test cases to database table

    Args:
        tool_id: unqiue Tool ID used in MCP-CF
        test_cases: list of generated test cases, each test case is a dictionary object
        run_status: status of test case generation request such as in-progess, complete , failed
        db: DB session to access the database

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> # Setup: Get the current module path dynamically to ensure patch works regardless of file location
        >>> mod_path = populate_testcases_table.__module__

        >>> # Case 1: Insert New Record (Tool ID not found in DB)
        >>> mock_db = MagicMock()
        >>> # Simulate query returning None (record does not exist)
        >>> mock_db.query.return_value.filter_by.return_value.first.return_value = None

        >>> # Patch the TestCaseRecord class specifically in THIS module
        >>> with patch(f"{mod_path}.TestCaseRecord") as MockRecord:
        ...     populate_testcases_table("tool-123", [{"test": "case"}], "in-progress", mock_db)
        ...
        ...     # Verify the class was instantiated
        ...     MockRecord.assert_called_with(tool_id="tool-123", test_cases=[{"test": "case"}], run_status="in-progress")
        ...     # Verify DB interactions
        ...     mock_db.add.assert_called()
        ...     mock_db.commit.assert_called()

        >>> # Case 2: Update Existing Record
        >>> mock_db_update = MagicMock()
        >>> existing_record = MagicMock()
        >>> mock_db_update.query.return_value.filter_by.return_value.first.return_value = existing_record

        >>> # We still patch TestCaseRecord to ensure no side effects, though it's not instantiated here
        >>> with patch(f"{mod_path}.TestCaseRecord"):
        ...     populate_testcases_table("tool-123", [{"test": "new"}], "completed", mock_db_update)
        ...
        ...     # Verify fields were updated on existing record
        ...     assert existing_record.test_cases == [{"test": "new"}]
        ...     assert existing_record.run_status == "completed"
        ...     # Verify add was NOT called
        ...     mock_db_update.add.assert_not_called()
    """
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    if not tool_record:
        test_case_record = TestCaseRecord(tool_id=tool_id, test_cases=test_cases, run_status=run_status)
        # Add to DB
        db.add(test_case_record)
        db.commit()
        db.refresh(test_case_record)
        logger.info("Added tool test case record with empty test cases for tool " + str(tool_id) + " with status " + str(run_status))
    # elif tool_record and test_cases != [] and run_status == 'completed':
    elif tool_record:
        tool_record.test_cases = test_cases
        tool_record.run_status = run_status
        db.commit()
        db.refresh(tool_record)
        logger.info("Updated tool record in table with test cases for tool " + str(tool_id) + " with status " + str(run_status))


def query_testcases_table(tool_id, db: Session):
    """
    Method to read toolops test cases from database table

    Args:
        tool_id: unqiue Tool ID used in MCP-CF
        db: DB session to access the database

    Returns:
        This method returns tool record for specified tool id and tool record contains 'tool_id','test_cases','run_status'.

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> mock_db = MagicMock()

        >>> # Create a dummy record to return
        >>> mock_record = MagicMock()
        >>> mock_record.tool_id = "tool-abc"
        >>> mock_record.test_cases = [{"input": "test"}]

        >>> # Mock the chain: db.query(...).filter_by(...).first()
        >>> mock_db.query.return_value.filter_by.return_value.first.return_value = mock_record

        >>> # Execute
        >>> result = query_testcases_table("tool-abc", mock_db)

        >>> # Verify result and calls
        >>> result.tool_id
        'tool-abc'
        >>> mock_db.query.assert_called()
    """
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    logger.info("Tool record obtained from table for tool - " + str(tool_id))
    return tool_record


def query_tool_auth(tool_id, db: Session):
    """
    Method to read tools table from database and get tool auth

    Args:
        tool_id: unique Tool ID used in MCP-CF
        db: DB session to access the database

    Returns:
        This method returns tool auth specified tool id.

    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> mod_path = query_tool_auth.__module__

        >>> # Case 1: Successful Auth Retrieval
        >>> mock_db = MagicMock()
        >>> mock_tool_record = MagicMock()
        >>> mock_tool_record.auth_value = "encoded-val"
        >>> mock_db.query.return_value.filter_by.return_value.first.return_value = mock_tool_record

        >>> # We nest the patches to avoid SyntaxError in doctest multiline 'with' statements
        >>> with patch(f"{mod_path}.decode_auth", side_effect=lambda x: f"decoded-{x}"):
        ...     with patch(f"{mod_path}.Tool"):
        ...         auth = query_tool_auth("tool-1", mock_db)
        ...         print(auth)
        decoded-encoded-val

        >>> # Case 2: Exception Handling
        >>> mock_db_fail = MagicMock()
        >>> mock_db_fail.query.side_effect = Exception("DB Connection Error")

        >>> with patch(f"{mod_path}.Tool"):
        ...     auth = query_tool_auth("tool-2", mock_db_fail)
        ...     print(auth)
        None
    """
    tool_auth = None
    try:
        tool_record = db.query(Tool).filter_by(id=tool_id).first()
        tool_auth = decode_auth(tool_record.auth_value)
        logger.info("Tool auth obtained from table for the tool - " + str(tool_id))
    except Exception as e:
        logger.error("Error in obtaining authorization for the tool - " + tool_id + " , " + str(e))
    return tool_auth


# if __name__=='__main__':
#     # First-Party
#     from mcpgateway.db import SessionLocal
#     from mcpgateway.services.tool_service import ToolService

#     tool_id = '36451eb11de64ebf8f224fc41a846ff0'
#     tool_service = ToolService()
#     db = SessionLocal()

#     tool_auth = query_tool_auth(tool_id, db)
#     print(tool_auth)
