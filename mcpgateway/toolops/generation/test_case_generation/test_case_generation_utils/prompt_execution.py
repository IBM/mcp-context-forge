import os
import sys
import json
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods
from toolops.utils.llm_util import execute_prompt
import numpy as np
import logging
import re

logger = logging.getLogger('toolops.generation.test_case_generation.test_case_generation_utils.prompt_execution')
parent_dir = os.path.dirname(os.path.join(os.getcwd(),"src"))
sys.path.append(parent_dir)

def data_using_LLM(prompt, model_id, llm_platform):
    parameters = {
        # GenParams.DECODING_METHOD: 'sample',
        GenParams.RANDOM_SEED: np.random.randint(1, 50),
        GenParams.MIN_NEW_TOKENS: 0,
        GenParams.MAX_NEW_TOKENS: 1000,
        GenParams.DECODING_METHOD: DecodingMethods.GREEDY.value,
        GenParams.REPETITION_PENALTY: 1,
        GenParams.STOP_SEQUENCES: [],
        GenParams.TEMPERATURE: 0.7,
        GenParams.TOP_K: 50,
        GenParams.TOP_P: 1
    }

    model_id = os.environ.get('TCG_MODEL_ID', model_id)
    response_trimmed = execute_prompt(prompt, model_id, llm_platform, parameters=parameters)
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