import os
import sys
import json
import re
from mcpgateway.toolops.utils.llm_util import execute_prompt


from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

def data_using_LLM(prompt, model_id, llm_platform):
    response_trimmed = execute_prompt(prompt, model_id)
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
    return(response_from_LLM)

def post_process_testcase(response_from_LLM):
    response_from_LLM = response_from_LLM.replace("\_", "_")
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
            case_json = json.loads(case)
            count=count+1
            key = list(case_json.keys())[0]
            processed_response_from_LLM[key] = case_json[key]
        except:
            pass
    return(processed_response_from_LLM)