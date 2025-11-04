import os
import sys
import json
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.prompt_execution import data_using_LLM, post_process_testcase

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# This method generates one testcase with all paramteres #
def all_param_testcase(transformed_tool_spec, data_generated_through_LLM, number_testcases_to_generate_more, transformed_tool_spec_postprocess, llm_model_id, llm_platform):
    number_of_tries = 0
    data_generated_through_LLM["testcase_1"] = dict()
    operation_type = list(transformed_tool_spec_postprocess["operation"].keys())[0]
    all_keys=list()
    if len(set(transformed_tool_spec_postprocess["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
        for param_type in ["request_body_params", "query_params", "path_params"]: 
            for key in transformed_tool_spec_postprocess["operation"][operation_type][param_type]:
                all_keys.append(key)
        if len(transformed_tool_spec_postprocess["operation"][operation_type]["request_body_params"].keys())>0:
            all_keys.append("__requestBody__")
    else:
        for key in transformed_tool_spec_postprocess["operation"][operation_type]:
            all_keys.append(key)
    while (number_of_tries <= 1):
        number_of_tries=number_of_tries+1
        incorrectly_generated_data=True
        data_generated_through_LLM_so_far = dict()
        count_failed_execution=0
        while(incorrectly_generated_data):
            try:
                prompt = """You are expert in generating one testcase with realistic values without the word 'example_' for all the parameters present in a spec. Currently I have an incomplete testcase such as\n"""+json.dumps(data_generated_through_LLM["testcase_1"])+"""\n You need to generate the realistic values without 'example_' for the remaining parameters. In one testcase you never exclude any parameters. Generate """+str(1)+""" testcase with all the parameters for the following spec where for the testcase provide the parameter and the corresponding value. If "example" values are given for a parameter then only use those values in testcases for the parameter. Do not generate a value '' or ' ' for any parameters. Do not use any parameter named "extra_param" if it is not in the specification. Do not use "None" as a value for parameter. Check if values are generated for all parameters. If not respond '{}'. The generated text should be in a dictionary format such as {“testcase_1”: {“parameter 1”: “value 1”, “parameter 2”: “value 2”, ...}.\n"""+json.dumps(transformed_tool_spec)+"""\n"""
                data_generated_through_LLM_so_far = post_process_testcase(data_using_LLM(prompt, llm_model_id, llm_platform))
                correctly_generated_values=True
                if len(data_generated_through_LLM_so_far) > 0:
                    for case in data_generated_through_LLM_so_far: 
                        for key in list(data_generated_through_LLM_so_far[case].keys()):
                            if data_generated_through_LLM_so_far[case][key] == '' or data_generated_through_LLM_so_far[case][key] == ' ':
                                correctly_generated_values=False
                                break
                else:
                    correctly_generated_values=False
                if correctly_generated_values == True:
                    incorrectly_generated_data=False
                    for case in data_generated_through_LLM_so_far:
                        for key in list(data_generated_through_LLM_so_far[case].keys()):
                            if key not in list(data_generated_through_LLM["testcase_1"].keys()) and key in all_keys:
                                data_generated_through_LLM["testcase_1"][key] = data_generated_through_LLM_so_far[case][key]
                        break
            except Exception as e:
                logger.info("Error is generating test cases for - all params"+str(e))
                incorrectly_generated_data=True
            count_failed_execution=count_failed_execution+1
            if (count_failed_execution == 2):
                break
    #logger.info("One testcase generated with all parameters",extra={'details':data_generated_through_LLM})
    logger.info("One testcase generated with all parameters")
    number_testcases_to_generate_more = number_testcases_to_generate_more - 1
    return(data_generated_through_LLM, number_testcases_to_generate_more)