import os
import sys
import copy
import logging

logger = logging.getLogger('toolops.generation.test_case_generation.test_case_generation_utils.combination_modules.mandatory_param_testcase')
parent_dir = os.path.dirname(os.path.join(os.getcwd(),"src"))
sys.path.append(parent_dir)

# This funcmethodtion generates a testcase with only mandatory paramters derived from all paramter testcase #
def mandatory_param_testcase(transformed_tool_spec, data_generated_through_LLM, number_testcases_to_generate_more, count_testcases):
    if "testcase_1" in data_generated_through_LLM:
        if len(data_generated_through_LLM["testcase_1"]) > 0:
            required_keys = []
            operation_type = list(transformed_tool_spec["operation"].keys())[0]
            if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
                for param_type in ["request_body_params", "query_params", "path_params"]: 
                    for key in transformed_tool_spec["operation"][operation_type][param_type]:
                        if transformed_tool_spec["operation"][operation_type][param_type][key]["required"] == "True":
                            required_keys.append(key)
            else:
                for key in transformed_tool_spec["operation"][operation_type]:
                    if transformed_tool_spec["operation"][operation_type][key]["required"] == "True":
                        required_keys.append(key)
    
            temp_mandatory_testcase=dict()
            data_generated_through_LLM_copy = copy.deepcopy(data_generated_through_LLM["testcase_1"])
            if "__requestBody__" in data_generated_through_LLM_copy:
                for key in list(data_generated_through_LLM_copy["__requestBody__"].keys()):
                    data_generated_through_LLM_copy[key] = data_generated_through_LLM_copy["__requestBody__"][key]
            for key in list(data_generated_through_LLM_copy.keys()):
                if key in required_keys:
                    temp_mandatory_testcase[key] = data_generated_through_LLM_copy[key]
            if len(temp_mandatory_testcase)>0:
                data_generated_through_LLM["testcase_2"] = temp_mandatory_testcase
                number_testcases_to_generate_more = number_testcases_to_generate_more-1
                count_testcases=count_testcases+1
    logger.info("One testcase generated with only mandatory parameters",extra={'details':{"testcase_2":data_generated_through_LLM["testcase_2"]}})
    return(data_generated_through_LLM, number_testcases_to_generate_more, count_testcases)