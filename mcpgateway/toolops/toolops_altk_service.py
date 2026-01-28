# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/toolops_altk_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Main module for toolops services.

This module defines the different toolops services

Features and Responsibilities:
- Automated test case generation for a tool
- Tool meta-data enrichment,
- Tool NL test cases execution with MCP server using an agent.

Structure:
- Import necessary required toolops modules from ALTK package
- Overriding ALTK LLM inference modules with MCP-CF inference modules
- Creating services for toolops functionalities
"""

# Standard
import os
from typing import Any

# Third-Party
import orjson

try:
    # Third-Party
    from altk.build_time.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment import prompt_utils
    from altk.build_time.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment.enrichment import ToolOpsMCPCFToolEnrichment
    from altk.build_time.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation import NlUtteranceGeneration
    from altk.build_time.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation_utils import nlg_util
    from altk.build_time.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation import TestcaseGeneration
    from altk.build_time.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation_utils import prompt_execution
    from altk.build_time.test_case_generation_toolkit.src.toolops.utils import llm_util
except ImportError:
    prompt_utils = None
    ToolOpsMCPCFToolEnrichment = None
    NlUtteranceGeneration = None
    nlg_util = None
    TestcaseGeneration = None
    prompt_execution = None
    llm_util = None

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.schemas import ToolRead, ToolUpdate
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_client_chat_service import LLMConfig, MCPChatService, MCPClientConfig, MCPServerConfig
from mcpgateway.services.tool_service import ToolService
from mcpgateway.toolops.utils.db_util import populate_testcases_table, query_testcases_table, query_tool_auth
from mcpgateway.toolops.utils.format_conversion import convert_to_toolops_spec, post_process_nl_test_cases
from mcpgateway.toolops.utils.llm_util import get_llm_instance

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


toolops_llm_provider = os.getenv("LLM_PROVIDER")
toolops_llm, toolops_llm_provider_config = get_llm_instance()
if toolops_llm is not None and toolops_llm_provider_config is not None:
    TOOLOPS_LLM_CONFIG = LLMConfig(provider=toolops_llm_provider, config=toolops_llm_provider_config)
else:
    logger.error("Error in obtaining LLM instance for Toolops services")
    TOOLOPS_LLM_CONFIG = None

LLM_MODEL_ID = os.getenv("OPENAI_MODEL", "")
provider = os.getenv("OPENAI_BASE_URL", "")
LLM_PLATFORM = "OpenAIProvider - " + provider


# ---------------
# IMPORTANT NOTE:
# ---------------
# ALTK (agent life cycle toolkit) does not support all LLM providers that are supported in MCP context forge.
# To use all MCP CF supported LLM providers we need to override the ALTK modules related to LLM inferencing.
# i.e; `execute_prompt` method used in different ALTK toolops modules is overrided with custom execute prompt
# that uses MCP context forge LLM inferencing modules.


#  custom execute prompt to support MCP-CF LLM providers
def custom_mcp_cf_execute_prompt(prompt, client=None, gen_mode=None, parameters=None, max_new_tokens=600, stop_sequences=None):
    """
    Custom execute prompt method to support MCP-CF LLM providers and this method is used to override several Toolops modules 'execute_prompt' method for LLM inferencing.Since we are overriding the method few dummy inputs such as 'client,gen_mode,parameters,max_new_tokens' are retained and assigned with None value

    Args:
        prompt: User provided prompt/input for LLM inferencing
        client: ALTK specific LLM client, default is None
        gen_mode: ALTK specific LLM client generation mode , default is None
        parameters : ALTK specific LLM inferencing parameters , default is None
        max_new_tokens: ALTK specific LLM parameter , default is None
        stop_sequences: List of stop sequences to be used in LLM inferencing

    Returns:
        response: LLM output for the given prompt
    """
    try:
        logger.info("LLM Inference call using MCP-CF LLM provider")
        # To suppress pylint errors creating dummy altk params and asserting
        altk_dummy_params = {"client": client, "gen_mode": gen_mode, "parameters": parameters, "max_new_tokens": max_new_tokens, "stop_sequences": stop_sequences}
        logger.debug(altk_dummy_params)
        chat_llm_instance, _ = get_llm_instance(model_type="chat")
        llm_response = chat_llm_instance.invoke(prompt)
        response = llm_response.content
        return response
    except Exception as e:
        logger.error("Error in LLM Inference call usinf MCP-CF LLM provider - " + orjson.dumps({"Error": str(e)}).decode())
        return ""


# overriding methods (replace ALTK llm inferencing methods with MCP CF methods)
if llm_util:
    llm_util.execute_prompt = custom_mcp_cf_execute_prompt

if prompt_execution:
    prompt_execution.execute_prompt = custom_mcp_cf_execute_prompt

if nlg_util:
    nlg_util.execute_prompt = custom_mcp_cf_execute_prompt

if prompt_utils:
    prompt_utils.execute_prompt = custom_mcp_cf_execute_prompt


# Test case generation service method
async def validation_generate_test_cases(tool_id, tool_service: ToolService, db: Session, number_of_test_cases=2, number_of_nl_variations=1, mode="generate"):
    """
    Method for the service to generate tool test cases using toolops modules

    Args:
        tool_id: Unique tool id in MCP-CF
        tool_service (ToolService): Tool service to obtain the tool from database
        db (Session): DB session to connect with database
        number_of_test_cases: Maximum of number of tool test cases to be generated , default is 2
        number_of_nl_variations: Number of natural language variations(paraphrases) to be generated for each test case , default is 1
        mode: Refers to service execution mode , supported values - 'generation' , 'query' , 'status' \
               - in 'generation' mode test case generation is triggered, test cases are generated afresh and stored in database \
               - in 'query' mode test cases related to the tool in the database are retreived after test case generation is completed \
               - in 'status' mode provides test case generation status ie; 'in-progress','failed','completed'

    Returns:
        test_cases: list of tool test cases
    """
    test_cases = []
    try:
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        # check if test case generation is required
        if mode == "generate":
            logger.info(
                "Generating test cases for tool - " + str(tool_id) + "," + orjson.dumps({"number_of_test_cases": number_of_test_cases, "number_of_nl_variations": number_of_nl_variations}).decode()
            )
            mcp_cf_tool = tool_schema.to_dict(use_alias=True)
            if mcp_cf_tool is not None:
                wxo_tool_spec = convert_to_toolops_spec(mcp_cf_tool)
                populate_testcases_table(tool_id, test_cases, "in-progress", db)
                tc_generator = TestcaseGeneration(client=None, gen_mode=None, max_number_testcases_to_generate=number_of_test_cases)
                ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)
                nl_generator = NlUtteranceGeneration(client=None, gen_mode=None, max_nl_utterances=number_of_nl_variations)
                nl_test_cases = nl_generator.generate_nl(ip_test_cases)
                test_cases = post_process_nl_test_cases(nl_test_cases)
                populate_testcases_table(tool_id, test_cases, "completed", db)
        elif mode == "query":
            # check if tool test cases generation is complete and get test cases
            tool_record = query_testcases_table(tool_id, db)
            if tool_record:
                if tool_record.run_status == "completed":
                    test_cases = tool_record.test_cases
                    logger.info("Obtained exisitng test cases from the table for tool " + str(tool_id))
        elif mode == "status":
            # check the test case generation status
            tool_record = query_testcases_table(tool_id, db)
            if tool_record:
                status = tool_record.run_status
                test_cases = [{"status": status, "tool_id": tool_id}]
                logger.info("Test case generation status for the tool -" + str(tool_id) + ", status -" + str(status))
            else:
                test_cases = [{"status": "not-initiated", "tool_id": tool_id}]
                logger.info("Test case generation is not initiated for the tool " + str(tool_id))
    except Exception as e:
        error_message = "Error in generating test cases for tool - " + str(tool_id) + " , details - " + str(e)
        logger.info(error_message)
        test_cases = [{"status": "error", "error_message": error_message, "tool_id": tool_id}]
        populate_testcases_table(tool_id, test_cases, "failed", db)
    return test_cases


async def execute_tool_nl_test_cases(tool_id, tool_nl_test_cases, tool_service: ToolService, db: Session):
    """
    Method for the service to execute tool nl test cases with MCP server using agent.

    Args:
        tool_id: Unique tool id in MCP-CF
        tool_nl_test_cases: List of tool invoking utternaces for testing the tool with Agent
        tool_service: Tool service to obtain the tool from database
        db: DB session to connect with database

    Returns:
        tool_test_case_outputs: list of tool outputs after tool test cases execution with agent.
    """
    tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
    mcp_cf_tool = tool_schema.to_dict(use_alias=True)
    tool_url = mcp_cf_tool.get("url")
    tool_auth = query_tool_auth(tool_id, db)
    # handling transport based on protocol type
    if "/mcp" in tool_url:
        config = MCPClientConfig(mcp_server=MCPServerConfig(url=tool_url, transport="streamable_http", headers=tool_auth), llm=TOOLOPS_LLM_CONFIG)
    elif "/sse" in tool_url:
        config = MCPClientConfig(mcp_server=MCPServerConfig(url=tool_url, transport="sse", headers=tool_auth), llm=TOOLOPS_LLM_CONFIG)
    else:
        config = MCPClientConfig(mcp_server=MCPServerConfig(url=tool_url, transport="stdio", headers=tool_auth), llm=TOOLOPS_LLM_CONFIG)

    service = MCPChatService(config)
    await service.initialize()
    logger.info("MCP tool server - " + str(tool_url) + " is ready for tool validation")

    tool_test_case_outputs = []
    # we execute each nl test case and if there are any errors we add that to test case output
    for nl_utterance in tool_nl_test_cases:
        try:
            tool_output = await service.chat(message=nl_utterance)
            tool_test_case_outputs.append(tool_output)
        except Exception as e:
            logger.info("Error in executing tool validation test cases with MCP server - " + str(e))
            tool_test_case_outputs.append(str(e))
            continue
    return tool_test_case_outputs


async def enrich_tool(tool_id: str, tool_service: ToolService, db: Session) -> tuple[str, ToolRead]:
    """
    Method for the service to enrich tool meta data such as tool description

    Args:
        tool_id: Unique tool id in MCP-CF
        tool_service: Tool service to obtain the tool from database
        db: DB session to connect with database

    Returns:
        enriched_description: Enriched tool description
        tool_schema: Updated tool schema in MCP-CF ToolRead format
    """
    try:
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        mcp_cf_tool = tool_schema.to_dict(use_alias=True)
    except Exception as e:
        logger.error(f"Failed to convert tool {tool_id} to schema: {e}")

    toolops_enrichment = ToolOpsMCPCFToolEnrichment(llm_client=None, gen_mode=None)
    enriched_description = await toolops_enrichment.enrich_mc_cf_tool(mcp_cf_toolspec=mcp_cf_tool)

    if enriched_description:
        try:
            update_data: dict[str, Any] = {
                "name": tool_schema.name,
                "description": enriched_description,
            }
            updated_tool: ToolUpdate = ToolUpdate(**update_data)
            updated_tool.name = tool_schema.name
            updated_tool.description = enriched_description
            await tool_service.update_tool(db, tool_id, updated_tool)
        except Exception as e:
            logger.error(f"Failed to update tool {tool_id} with enriched description: {e}")

    return enriched_description, tool_schema


# if __name__ == "__main__":
#     # Standard
#     import asyncio

#     # First-Party
#     from mcpgateway.db import SessionLocal
#     from mcpgateway.services.tool_service import ToolService

#     tool_id = "69df98bcab6b4895a0345a20aeb038b2"
#     tool_service = ToolService()
#     db = SessionLocal()
#     # tool_test_cases = asyncio.run(validation_generate_test_cases(tool_id, tool_service, db, number_of_test_cases=2, number_of_nl_variations=2, mode="generate"))
#     # print("#" * 30)
#     # print("tool_test_cases")
#     # print(tool_test_cases)
#     # enrich_output = asyncio.run(enrich_tool(tool_id, tool_service, db))
#     # print("#" * 30)
#     # print("enrich_output")
#     # print(enrich_output)
#     tool_nl_test_cases = ["add 3 and 10","please add 4 and 6"]
#     tool_outputs = asyncio.run(execute_tool_nl_test_cases(tool_id, tool_nl_test_cases, tool_service, db))
#     print("#" * 30)
#     print("len - tool_outputs", len(tool_outputs))
#     print(tool_outputs)
