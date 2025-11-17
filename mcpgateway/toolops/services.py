import json
import os
import base64
import datetime
from typing import Any
from sqlalchemy.orm import Session
import asyncio

from mcpgateway.db import ToolOpsTestCases as TestCaseRecord
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


def populate_testcases_table(tool_id,test_cases,run_status,db: Session):
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    if not tool_record:
        test_case_record = TestCaseRecord(tool_id= tool_id,test_cases= test_cases,run_status = run_status)
        # Add to DB
        db.add(test_case_record)
        db.commit()
        db.refresh(test_case_record)
        logger.info("Added tool test case record with empty test cases for tool "+str(tool_id)+" with status "+str(run_status))
    #elif tool_record and test_cases != [] and run_status == 'completed':
    elif tool_record:
        tool_record.test_cases = test_cases
        tool_record.run_status = run_status
        db.commit()
        db.refresh(tool_record)
        logger.info("Updated tool record in table with test cases for tool "+str(tool_id)+" with status "+str(run_status))
    

def query_testcases_table(tool_id,db: Session):
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    logger.info("Tool record obtained from table for tool - "+str(tool_id))
    return tool_record
            

# Test case generation service method
async def validation_generate_test_cases(tool_id,tool_service: ToolService, db: Session, number_of_test_cases=2,number_of_nl_variations=1,mode="generate"):
    test_cases = []
    try:
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        # check if test case generation is required
        if mode == "generate":
            logger.info("Generating test cases for tool - "+str(tool_id)+","+json.dumps({"number_of_test_cases":number_of_test_cases,"number_of_nl_variations":number_of_nl_variations}) )
            mcp_cf_tool = tool_schema.to_dict(use_alias=True)
            if mcp_cf_tool is not None:
                wxo_tool_spec = convert_to_wxo_tool_spec(mcp_cf_tool)
                populate_testcases_table(tool_id,test_cases,"in-progress",db)
                tc_generator = TestcaseGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_number_testcases_to_generate=number_of_test_cases)
                ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)
                nl_generator = NlUtteranceGeneration(llm_model_id=LLM_MODEL_ID, llm_platform=LLM_PLATFORM, max_nl_utterances=number_of_nl_variations)
                nl_test_cases = nl_generator.generate_nl(ip_test_cases)
                test_cases = post_process_nl_test_cases(nl_test_cases)
                populate_testcases_table(tool_id,test_cases,"completed",db)
        elif mode == 'query':
            # check if tool test cases generation is complete and get test cases
            tool_record = query_testcases_table(tool_id,db)
            if tool_record:
                if tool_record.run_status == 'completed':
                    test_cases = tool_record.test_cases
                    logger.info("Obtained exisitng test cases from the table for tool "+str(tool_id))
        elif mode == 'status':
            # check the test case generation status
            tool_record = query_testcases_table(tool_id,db)
            if tool_record :
                status = tool_record.run_status
                test_cases = [{'status':status,'tool_id':tool_id}]
                logger.info("Test case generation status for the tool -"+str(tool_id)+", status -"+str(status))
            else:
                test_cases = [{'status':'not-initiated','tool_id':tool_id}]
                logger.info("Test case generation is not initiated for the tool "+str(tool_id))
    except Exception as e:
        error_message = "Error in generating test cases for tool - "+str(tool_id)+" , details - "+str(e)
        logger.info(error_message)
        test_cases = [{"status":"error","error_message":error_message,"tool_id":tool_id}]
        populate_testcases_table(tool_id,test_cases,"failed",db)
    return test_cases

# Execute nl test cases with mcp tool service
from mcpgateway.services.mcp_client_chat_service import MCPChatService
from mcpgateway.services.mcp_client_chat_service import MCPClientConfig,MCPServerConfig,LLMConfig
from mcpgateway.toolops.utils.llm_util import get_llm_instance

toolops_llm_provider = os.getenv("LLM_PROVIDER")
_,toolops_llm_provider_config = get_llm_instance()
toolops_llm_config = LLMConfig(provider=toolops_llm_provider,config=toolops_llm_provider_config)

async def execute_tool_nl_test_cases(tool_id,tool_nl_test_cases,tool_service: ToolService, db: Session):
    tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
    mcp_cf_tool = tool_schema.to_dict(use_alias=True)
    tool_url = mcp_cf_tool.get('url')
    mcp_server_url = tool_url.split("/sse")[0]+"/mcp"
    config = MCPClientConfig(
            mcp_server=MCPServerConfig(url=mcp_server_url,transport="streamable_http"),
            llm=toolops_llm_config
        )
    service = MCPChatService(config)
    await service.initialize()
    logger.info("MCP tool server - "+str(mcp_server_url)+" is ready for tool validation")

    tool_test_case_outputs = []
    # we execute each nl test case and if there are any errors we add that to test case output
    for nl_utterance in tool_nl_test_cases:
        try:
            tool_output= await service.chat(message=nl_utterance)
            tool_test_case_outputs.append(tool_output)
        except Exception as e:
            logger.info("Error in executing tool validation test cases with MCP server - "+str(e))
            tool_test_case_outputs.append(str(e))
            pass
    return tool_test_case_outputs

# Enrichment service method
def get_unique_sessionid() -> str:
    timestamp = ""
    timestamp = datetime.datetime.now().strftime(
        "%Y-%m-%dT%H-%M-%S.%fZ-"
    ) + base64.urlsafe_b64encode(os.urandom(6)).decode("ascii")

    return timestamp

# async def enrich_tool_list(tool_id_list: list[str], tool_service: ToolService, db: Session, LLM_PLATFORM: str = 'WATSONX',LLM_MODEL_ID: str = 'mistralai/mistral-medium-2505')-> tuple[list[str], list[ToolRead]]:
#     enriched_description_lst: list[str] = []
#     tool_schema_lst: list[ToolRead]  = [] 
#     for _idx, tool_id in enumerate(tool_id_list):
#         enriched_description, tool_schema = await enrich_tool(tool_id, tool_service, db, LLM_PLATFORM,LLM_MODEL_ID)
#         enriched_description_lst.append(enriched_description)
#         tool_schema_lst.append(tool_schema)

#     return enriched_description_lst, tool_schema_lst


async def enrich_tool(tool_id: str, tool_service: ToolService, db: Session)-> tuple[str, ToolRead]:
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
    from mcpgateway.services.tool_service import ToolService
    from mcpgateway.db import SessionLocal
    tool_service = ToolService()
    db = SessionLocal()
    tool_id = 'ccf65855a34e403f97c8d801bee1906f'
    tool_nl_test_cases = ['get all actions', 'get salesloft actions','I need salesloft all actions']
    tool_outputs=asyncio.run(execute_tool_nl_test_cases(tool_id,tool_nl_test_cases,tool_service, db))
    print("#"*30)
    print(tool_outputs)
    print("len - tool_outputs",len(tool_outputs))

