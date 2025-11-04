import json
import os
import base64
import datetime
from typing import Any
from sqlalchemy.orm import Session

from mcpgateway.services.tool_service import ToolService
from mcpgateway.schemas import ToolRead, ToolUpdate
from mcpgateway.toolops.enrichment.enrichment import ToolOpsEnrichment
from mcpgateway.toolops.utils.tool_format_conversion import convert_to_wxo_tool_spec,post_process_nl_test_cases
from mcpgateway.toolops.generation.test_case_generation.test_case_generation import TestcaseGeneration
from mcpgateway.toolops.generation.nl_utterance_generation.nl_utterance_generation import NlUtteranceGeneration

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

LLM_MODEL_ID = os.getenv("OPENAI_MODEL","")
provider = os.getenv("OPENAI_BASE_URL","")
LLM_PLATFORM = "OpenAIProvider - "+provider


# Test case generation service method
async def validation_generate_test_cases(tool_id,tool_service: ToolService, db: Session, number_of_test_cases=2,number_of_nl_variations=1):
    test_cases = []
    try:
        logger.info("Generating test cases for tool - "+str(tool_id))
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        mcp_cf_tool = tool_schema.to_dict(use_alias=True)
        if mcp_cf_tool is not None:
            wxo_tool_spec = convert_to_wxo_tool_spec(mcp_cf_tool)
            tc_generator = TestcaseGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_number_testcases_to_generate=number_of_test_cases)
            ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)

            nl_generator = NlUtteranceGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_nl_utterances=number_of_nl_variations)
            nl_test_cases = nl_generator.generate_nl(ip_test_cases)
            test_cases = post_process_nl_test_cases(nl_test_cases)
    except Exception as e:
        error_message = "Error in generating test cases for tool - "+str(tool_id)+" , details - "+str(e)
        logger.info(error_message)
        test_cases = [{"error":error_message}]
    return test_cases
    

# Enrichment service method
def get_unique_sessionid() -> str:
    timestamp = ""
    timestamp = datetime.datetime.now().strftime(
        "%Y-%m-%dT%H-%M-%S.%fZ-"
    ) + base64.urlsafe_b64encode(os.urandom(6)).decode("ascii")

    return timestamp

async def enrich_tool_list(tool_id_list: list[str], tool_service: ToolService, db: Session, LLM_PLATFORM: str = 'WATSONX',LLM_MODEL_ID: str = 'mistralai/mistral-medium-2505')-> tuple[list[str], list[ToolRead]]:
    enriched_description_lst: list[str] = []
    tool_schema_lst: list[ToolRead]  = [] 
    for _idx, tool_id in enumerate(tool_id_list):
        enriched_description, tool_schema = await enrich_tool(tool_id, tool_service, db, LLM_PLATFORM,LLM_MODEL_ID)
        enriched_description_lst.append(enriched_description)
        tool_schema_lst.append(tool_schema)

    return enriched_description_lst, tool_schema_lst


async def enrich_tool(tool_id: str, tool_service: ToolService, db: Session, LLM_PLATFORM: str = 'WATSONX',LLM_MODEL_ID: str = 'mistralai/mistral-medium-2505')-> tuple[str, ToolRead]:
    try:
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
    except Exception as e:
        logger.error(f"Failed to convert tool {tool_id} to schema: {e}")   
        raise e

    toolops_enrichment = ToolOpsEnrichment(LLM_MODEL_ID, LLM_PLATFORM)
    enriched_description = await toolops_enrichment.process(tool_schema)

    if enriched_description:
        try:
            update_data: dict[str, Any] = {
                "name": tool_schema.name,
                "description": enriched_description,
            }
            updateTool: ToolUpdate = ToolUpdate(**update_data)
            updateTool.name = tool_schema.name
            updateTool.description = enriched_description
            await tool_service.update_tool(db, tool_id, updateTool)
        except Exception as e:
            logger.error(f"Failed to update tool {tool_id} with enriched description: {e}")   
            raise e

    return enriched_description, tool_schema

if __name__=='__main__':
    tool_id = "e228725d951f4877bcb80418e7a6f139"
    test_cases = validation_generate_test_cases(tool_id)
    print(test_cases)