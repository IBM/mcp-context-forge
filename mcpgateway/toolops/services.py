import json
import os
from mcpgateway.toolops.tool_format_conversion import convert_to_wxo_tool_spec
from toolops.validation.test_case_generation import TestcaseGeneration
from toolops.validation.nl_utterance_generation import NlUtteranceGeneration



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
            

async def validation_generate_test_cases(tool_id,LLM_PLATFORM = 'WATSONX',LLM_MODEL_ID = 'mistralai/mistral-medium-2505',
                                   NUMBER_OF_TESTCASES = 5,NUMBER_OF_UTTERANCES = 2):
    test_cases = []
    try:
        mcp_cf_tool=get_mcp_cf_tool(tool_id)
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