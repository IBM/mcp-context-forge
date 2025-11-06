import json
import re
from mcpgateway.toolops.utils.llm_util import execute_prompt


from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

def data_using_LLM(prompt, model_id, llm_platform):

    response_trimmed = execute_prompt(prompt)
    response_portion = response_trimmed
    if "```" in response_trimmed:
        response_portion = response_trimmed.split("```")[1]
    if "python" in response_portion:
        if "testcases =" in response_portion.split("python")[1]:
            response_from_LLM = response_portion.split("python")[1].split("testcases =")[1]
        else:
            response_from_LLM = response_portion.split("python")[1]
    elif "json" in response_portion:
        if "testcases =" in response_portion.split("json")[1]:
            response_from_LLM = response_portion.split("json")[1].split("testcases =")[1]
        else:
            response_from_LLM = response_portion.split("json")[1]
    else:
        response_from_LLM = response_portion
    try:
        json.loads(response_from_LLM)
    except:
        valid_jsons = []
        stack = 0
        start = None
        num_testcase=0
        for i, ch in enumerate(response_from_LLM):
            if ch == '{':
                if stack == 0:
                    start = i
                stack += 1
            elif ch == '}':
                stack -= 1
                if stack in [0,1] and start is not None:
                    snippet = response_from_LLM[start:i+1]
                    try:
                        num_testcase=num_testcase+1
                        if stack==1:
                            snippet = snippet+"}"
                        if "testcase_" not in snippet:
                            snippet = {"testcase_"+str(num_testcase):json.loads(snippet)}
                        if isinstance(snippet, str):
                            data = json.loads(snippet)
                        else:
                            data=snippet
                        valid_jsons.append(data)
                    except json.JSONDecodeError:
                        pass  
                    start = None
                    stack=0

        merged = {}
        for item in valid_jsons:
            if isinstance(item, dict):
                merged.update(item)
        if len(merged) > 0:
            response_from_LLM = merged
        else:
            response_from_LLM = "No json found"
    print("response_from_LLM",response_from_LLM)
    return(response_from_LLM)

def post_process_testcase(response_from_LLM):
    if isinstance(response_from_LLM, dict):
        response_from_LLM = json.dumps(response_from_LLM)
    response_from_LLM = response_from_LLM.replace(r"\_", "_")
    response_from_LLM = response_from_LLM.replace("\n", "")
    response_from_LLM = response_from_LLM.replace("\t", "")
    response_from_LLM = re.sub(r'\s+', ' ', response_from_LLM).strip()
    response_from_LLM = response_from_LLM.replace(": { ", ":{")
    response_from_LLM = response_from_LLM.replace("}, ", "},") 
    response_from_LLM = response_from_LLM.replace("{ ", "{")
    response_from_LLM = response_from_LLM.replace(" }", "}")
    response_from_LLM = response_from_LLM.split("testcase")
    processed_response_from_LLM = dict()
    count=0
    for case in response_from_LLM:
        try:
            changes_done=False
            if "Testcase" in case:
                case=case.split("}Testcase")[0]
                case = '{"testcase'+case
                case=case+"}"
                changes_done=True
            if "TestCase" in case:
                case=case.split("TestCase")[0]
                case=case[:-3]
                case = '{"testcase'+case
                changes_done=True
            if "}}" == case[-2:] and changes_done==False:
                case = '{"testcase'+case
            if ")" in case[-3:]:
                case = case[:-4]
                case = '{"testcase'+case
            if "," in case[-2:]:
                case=case[:-2]
                case = '{"testcase'+case
                case=case+"}"
            elif "{" in case[-2:]:
                case=case[:-3]
                if "}}" == case[-2:]:
                    case = '{"testcase'+case    
                else:
                    case = '{"testcase'+case
                    case=case+"}"
            case = case.replace("False", "false").replace("True", "true")
            case_json = json.loads(case)
            count=count+1
            key = list(case_json.keys())[0]
            processed_response_from_LLM[key] = case_json[key]
        except:
            pass
    print("processed_response_from_LLM",processed_response_from_LLM)
    return(processed_response_from_LLM)