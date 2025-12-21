# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/toolops_router.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

Toolops Router Module

This module provides FastAPI endpoints for managing Toolops functionalities
.It supports tool test case generation , tool meta-data enrichment and tool
test case execution with an agent.

The module handles API endpoints created for several toolops features.

"""

# Standard
from typing import Any, Dict, List

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Query, status
import orjson
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.main import get_db
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.toolops.toolops_altk_service import enrich_tool, execute_tool_nl_test_cases, validation_generate_test_cases

# Initialize router
toolops_router = APIRouter(prefix="/toolops", tags=["Toolops"])

# Initialize services
tool_service = ToolService()

# Logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# ---------- Utility ----------


class ToolNLTestInput(BaseModel):
    """
    Toolops test input format to run NL test cases of a tool using agent

    Args:
        tool_id : Unique Tool ID
        tool_nl_test_cases: List of natural language test cases for testing MCP tool with the agent

    Returns:
        This class defines tool NL test input format and returns nothing.
    """

    tool_id: str | None = Field(default=None, title="Tool ID", max_length=300)
    tool_nl_test_cases: list | None = Field(default=None, title="List of natural language test cases for testing MCP tool with the agent")


# ---------- ROUTES ----------


# First-Party
# Toolops APIs - Generating test cases , Tool enrichment #
@toolops_router.post("/validation/generate_testcases")
async def generate_testcases_for_tool(
    tool_id: str = Query(None, description="Tool ID"),
    number_of_test_cases: int = Query(2, description="Maximum number of tool test cases"),
    number_of_nl_variations: int = Query(1, description="Number of NL utterance variations per test case"),
    mode: str = Query("generate", description="Three modes: 'generate' for test case generation, 'query' for obtaining test cases from DB , 'status' to check test generation status"),
    db: Session = Depends(get_db),
) -> List[Dict]:
    """
    Generate test cases for a tool

    This endpoint handles the automated test case generation for a tool by accepting
    a tool id . The `require_auth` dependency ensures that
    the user is authenticated before proceeding.

    Args:
        tool_id: Tool ID in context forge.
        number_of_test_cases: Number of test cases to generate for the given tools (optional)
        number_of_nl_variations: Number of Natural language variations(parapharses) per test case (optional)
        mode: Three supported modes - 'generate' for test case generation, 'query' for obtaining test cases from DB , 'status' to check test generation status
        db: DB session to connect with database

    Returns:
        List: A list of test cases generated for the tool , each test case is dictionary object

    Raises:
        HTTPException: If the request body contains invalid JSON, a 400 Bad Request error is raised.
    """
    try:
        # logger.debug(f"Authenticated user {user} is initializing the protocol.")
        test_cases = await validation_generate_test_cases(tool_id, tool_service, db, number_of_test_cases, number_of_nl_variations, mode)
        return test_cases

    except orjson.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body",
        )


@toolops_router.post("/validation/execute_tool_nl_testcases")
async def execute_tool_nl_testcases(tool_nl_test_input: ToolNLTestInput, db: Session = Depends(get_db)) -> List:
    """
    Execute test cases for a tool

    This endpoint handles the automated test case generation for a tool by accepting
    a tool id . The `require_auth` dependency ensures that
    the user is authenticated before proceeding.

    Args:
        tool_nl_test_input: NL test case format input to run test cases with agent , it contains\
            - tool_id: Tool ID in context forge\
            - tool_nl_test_cases: List of natural language test cases (utteances) for testing MCP tool with the agent
        db: DB session to connect with database

    Returns:
        List: A list of tool outputs after agent execution for the provided tool nl test cases

    Raises:
        HTTPException: If the request body contains invalid JSON, a 400 Bad Request error is raised.
    """
    try:
        # logger.debug(f"Authenticated user {user} is initializing the protocol.")
        tool_id = tool_nl_test_input.tool_id
        tool_nl_test_cases = tool_nl_test_input.tool_nl_test_cases
        tool_nl_test_cases_output = await execute_tool_nl_test_cases(tool_id, tool_nl_test_cases, tool_service, db)
        return tool_nl_test_cases_output

    except orjson.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body",
        )


@toolops_router.post("/enrichment/enrich_tool")
async def enrich_a_tool(tool_id: str = Query(None, description="Tool ID"), db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Enriches an input tool

    Args:
        tool_id: Unique Tool ID MCP-CF.
        db: The database session used to interact with the data store.

    Returns:
        result: A dict having the keys "tool_id", "tool_name", "original_desc" and "enriched_desc" with their corresponding values

    Raises:
        HTTPException: If the request body contains invalid JSON, a 400 Bad Request error is raised.
    """
    try:
        logger.info("Running tool enrichment for Tool - " + tool_id)
        enriched_tool_description, tool_schema = await enrich_tool(tool_id, tool_service, db)
        result: dict[str, Any] = {}
        result["tool_id"] = tool_id
        result["tool_name"] = tool_schema.name
        result["original_desc"] = tool_schema.description
        result["enriched_desc"] = enriched_tool_description
        # logger.info ("result: "+  json.dumps(result, indent=4, sort_keys=False))
        return result

    except Exception as e:
        logger.info("Error in tool enrichment for Tool - " + str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body" + str(e),
        ) from e
