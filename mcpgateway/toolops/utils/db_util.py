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
from mcpgateway.db import ToolOpsTestCases as TestCaseRecord
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def populate_testcases_table(tool_id, test_cases, run_status, db: Session):
    '''
    Method to write and update toolops test cases to database table
    Args:
        tool_id: unqiue Tool ID used in MCP-CF
        test_cases: list of generated test cases, each test case is a dictionary object
        run_status: status of test case generation request such as in-progess, complete , failed 
        db: DB session to access the database

    Returns:
        This method updates or writes tool test case records to database table and returns nothing.
    '''
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
    '''
    Method to read toolops test cases from database table
    Args:
        tool_id: unqiue Tool ID used in MCP-CF
        db: DB session to access the database

    Returns:
        This method returns tool record for specified tool id and tool record contains 'tool_id','test_cases','run_status'.
    '''
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    logger.info("Tool record obtained from table for tool - " + str(tool_id))
    return tool_record
