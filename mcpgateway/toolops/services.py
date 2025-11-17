import json
import os
import base64
import datetime
from typing import Any
from sqlalchemy.orm import Session
import asyncio


from mcpgateway.services.tool_service import ToolService
from mcpgateway.schemas import ToolRead, ToolUpdate
from mcpgateway.toolops.utils.db_util import populate_testcases_table,query_testcases_table
from mcpgateway.toolops.utils.tool_format_conversion import convert_to_wxo_tool_spec,post_process_nl_test_cases
from mcpgateway.toolops.utils.llm_util import completion_llm_instance
from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

LLM_MODEL_ID = os.getenv("OPENAI_MODEL","")
provider = os.getenv("OPENAI_BASE_URL","")
LLM_PLATFORM = "OpenAIProvider - "+provider

# importing toolops modules from ALTK
from altk.post_request.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment.enrichment import ToolOpsMCPCFToolEnrichment
from altk.post_request.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation import TestcaseGeneration
from altk.post_request.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation import NlUtteranceGeneration


'''
---------------
IMPORTANT NOTE:
--------------- 
ALTK (agent life cycle toolkit) does not support all LLM providers that are supported in MCP context forge. 
To use all MCP CF supported LLM providers we need to override the ALTK modules related to LLM inferencing. 
i.e; `execute_prompt` method used in different ALTK toolops modules is overrided with custom execute prompt
that uses MCP context forge LLM infercing modules.
'''

# custom execute prompt to support MCP-CF LLM providers
def custom_mcp_cf_execute_prompt(prompt, client = None, gen_mode = None, parameters=None, max_new_tokens=600, stop_sequences=["\n\n", "<|endoftext|>"]):
    try:
        logger.info("LLM Inference call using MCP-CF LLM provider")
        llm_response = completion_llm_instance.invoke(prompt, stop=stop_sequences)
        response = llm_response.replace("<|eom_id|>", "").strip()
        return response
    except Exception as e:
        logger.error('Error in LLM Inference call usinf MCP-CF LLM provider - '+json.dumps({'Error': str(e)}))
        return ""


# overriding methods (replace ALTK llm inferencing methods with MCP CF methods)
from altk.post_request.test_case_generation_toolkit.src.toolops.utils import llm_util
from altk.post_request.test_case_generation_toolkit.src.toolops.generation.test_case_generation.test_case_generation_utils import prompt_execution
from altk.post_request.test_case_generation_toolkit.src.toolops.generation.nl_utterance_generation.nl_utterance_generation_utils import nlg_util
from altk.post_request.test_case_generation_toolkit.src.toolops.enrichment.mcp_cf_tool_enrichment import prompt_utils
llm_util.execute_prompt = custom_mcp_cf_execute_prompt
prompt_execution.execute_prompt = custom_mcp_cf_execute_prompt
nlg_util.execute_prompt = custom_mcp_cf_execute_prompt
prompt_utils.execute_prompt = custom_mcp_cf_execute_prompt


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
                tc_generator = TestcaseGeneration(client=None,gen_mode=None,max_number_testcases_to_generate=number_of_test_cases)
                ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)
                nl_generator = NlUtteranceGeneration(client=None,gen_mode=None,max_nl_utterances=number_of_nl_variations)
                nl_test_cases = nl_generator.generate_nl(ip_test_cases)
                test_cases = post_process_nl_test_cases(nl_test_cases)
                populate_testcases_table(tool_id,test_cases,"completed",db)
                with open('tool_test_cases.json','w') as tf:
                    json.dump(test_cases,tf,indent=2)
                tf.close()
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


async def enrich_tool(tool_id: str, tool_service: ToolService, db: Session)-> tuple[str, ToolRead]:
    try:
        tool_schema: ToolRead = await tool_service.get_tool(db, tool_id)
        mcp_cf_tool = tool_schema.to_dict(use_alias=True)
    except Exception as e:
        logger.error(f"Failed to convert tool {tool_id} to schema: {e}")   
        raise e

    toolops_enrichment = ToolOpsMCPCFToolEnrichment(llm_client=None,gen_mode=None)
    enriched_description = await toolops_enrichment.enrich_mc_cf_tool(mcp_cf_toolspec=mcp_cf_tool)

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
    import asyncio
    tool_id = "ccf65855a34e403f97c8d801bee1906f"
    tool_service = ToolService()
    db = SessionLocal()
    asyncio.run(validation_generate_test_cases(tool_id,tool_service,db,number_of_test_cases=2,number_of_nl_variations=2,mode="generate"))
    enrich_output = asyncio.run(enrich_tool(tool_id, tool_service, db))
    print(enrich_output)
    tool_nl_test_cases = ['get all actions', 'get salesloft actions','I need salesloft all actions']
    tool_outputs=asyncio.run(execute_tool_nl_test_cases(tool_id,tool_nl_test_cases,tool_service, db))
    print("#"*30)
    print(tool_outputs)
    print("len - tool_outputs",len(tool_outputs))

