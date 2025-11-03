import json
import os
from mcpgateway.toolops.utils.tool_format_conversion import convert_to_wxo_tool_spec
from toolops.validation.test_case_generation import TestcaseGeneration
from toolops.validation.nl_utterance_generation import NlUtteranceGeneration
from mcpgateway.toolops.enrichment.enrichment import ToolOpsEnrichment
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.tool_service import ToolService
from mcpgateway.schemas import ToolRead, ToolUpdate
from sqlalchemy.orm import Session
import base64
import datetime
from typing import Any

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)



def get_mcp_cf_tool(tool_id):
    # Add code to get all available tools from MCP context forge
    pwd = os.getcwd()
    mcp_cf_tools = json.load(open(os.path.join('mcpgateway','toolops','list_of_tools_from_mcp_cf.json'),'r'))
    required_cf_tool = None
    for cf_tool in mcp_cf_tools:
        if cf_tool.get('id')==tool_id:
            required_cf_tool=cf_tool
            break
    return required_cf_tool
    
    
def post_process_nl_test_cases(nl_test_cases):
    test_cases = nl_test_cases.get('Test_scenarios')
    for tc in test_cases:
        for un_wanted in ['scenario_type','input']:
            del tc[un_wanted]
    return test_cases
            

async def validation_generate_test_cases(tool_id,tool_service: ToolService, db: Session,LLM_PLATFORM = 'WATSONX',LLM_MODEL_ID = 'mistralai/mistral-medium-2505',
                                   NUMBER_OF_TESTCASES = 5,NUMBER_OF_UTTERANCES = 2):
    test_cases = []
    try:
        #mcp_cf_tool=get_mcp_cf_tool(tool_id)
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        mcp_cf_tool = tool_schema.to_dict(use_alias=True)
        if mcp_cf_tool is not None:
            wxo_tool_spec = convert_to_wxo_tool_spec(mcp_cf_tool)
            tc_generator = TestcaseGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_number_testcases_to_generate=NUMBER_OF_TESTCASES)
            ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)

            nl_generator = NlUtteranceGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_nl_utterances=NUMBER_OF_UTTERANCES)
            nl_test_cases = nl_generator.generate_nl(ip_test_cases)
            test_cases = post_process_nl_test_cases(nl_test_cases)
        else:
            return "Tool ID - "+str(tool_id)+" doesn't exist"
    except Exception as e:
        print("Exception in validation_generate_test_cases - "+str(e))
        pass
    return test_cases
    

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


# from toolops.validation.nl_utterance_generation import NlUtteranceGeneration
# print("Generating NL test case")
# print("Example test case with tool testing nl utterance")
# generator = NlUtteranceGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_nl_utterances=NUMBER_OF_UTTERANCES)
# nl_test_cases = generator.generate_nl(test_cases)
# print("-"*100)
# pretty_print(nl_test_cases.get('Test_scenarios')[-1])
# print("-"*100)