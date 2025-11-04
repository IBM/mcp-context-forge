import os
import sys
import json
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.prompt_execution import data_using_LLM, post_process_testcase

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# This method generates testcases based on optional data provided by the user #
def generate_testcases_optional_data(transformed_tool_spec, optional_data_scenario, llm_model_id, llm_platform, max_number_testcases_to_generate):
    optional_data_scenario=optional_data_scenario[:max_number_testcases_to_generate]
    data_generated_through_LLM_from_optional_data=dict()
    required_keys = []
    operation_type = list(transformed_tool_spec["operation"].keys())[0]
    data_generated_through_LLM=dict()
    if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
        for param_type in ["request_body_params", "query_params", "path_params"]: 
            for key in transformed_tool_spec["operation"][operation_type][param_type]:
                if transformed_tool_spec["operation"][operation_type][param_type][key]["required"] == "True":
                    required_keys.append(key)
    else:
        for key in transformed_tool_spec["operation"][operation_type]:
            if transformed_tool_spec["operation"][operation_type][key]["required"] == "True":
                required_keys.append(key)

    num_testcases_to_generate_per_scenario_except_last = int(max_number_testcases_to_generate/len(optional_data_scenario))
    num_testcases_to_generate_per_scenario_last = max_number_testcases_to_generate - num_testcases_to_generate_per_scenario_except_last*(len(optional_data_scenario)-1)
    count_testcases=0
    correct_number_of_testcases_generated=False
    for scenario_index in range(len(optional_data_scenario)):
        if scenario_index < len(optional_data_scenario)-1:
            testcases_for_current_scenario = num_testcases_to_generate_per_scenario_except_last
        else:
            testcases_for_current_scenario = num_testcases_to_generate_per_scenario_last
        incorrectly_generated_data=True
        while(incorrectly_generated_data):
            try:
                prompt = """You are an expert in generating testcases with realistic values without the word 'example_' for a combination of mandatory and optional parameters present in a spec. Currently I have an incomplete testcase such as\n"""+json.dumps(optional_data_scenario[scenario_index])+"""\n For each testcase use the values of the all the parameters given in the incomplete testcase. In each of the testcase you never exclude any mandatory parameters. In each testcase you never exclude any optional parameter values that are given in the incomplete testcase. Do not generate any new values for the parameters given in the incomplete testcase. Generate """+str(testcases_for_current_scenario)+""" testcases for the following spec where for each of the generated testcases provide the parameter and the corresponding value. If "example" values are given for a parameter then only use those values in testcases for the parameter. Do not generate a value '' or ' ' for any parameters. Do not use any parameter named "extra_param" if it is not in the specification. Do not use "None" as a value for parameter. The generated text should be in a dictionary format such as {“testcase_1”: {“parameter 1”: “value 1”, “parameter 2”: “value 2”, ...}.\n"""+json.dumps(transformed_tool_spec)+"""\n"""
                data_generated_through_LLM_so_far = post_process_testcase(data_using_LLM(prompt, llm_model_id, llm_platform))
                incorrectly_generated_data=False
                for case in data_generated_through_LLM_so_far:
                    count_testcases=count_testcases+1
                    data_generated_through_LLM["testcase_"+str(count_testcases)] = data_generated_through_LLM_so_far[case]
                    data_generated_through_LLM_from_optional_data["testcase_"+str(count_testcases)] = data_generated_through_LLM_so_far[case]
                    if count_testcases == max_number_testcases_to_generate:
                        correct_number_of_testcases_generated=True
                        break
                if (correct_number_of_testcases_generated==True):
                    break
            except:
                count_failed_execution=count_failed_execution+1
                if count_failed_execution==3:
                    break
                incorrectly_generated_data=True
    #logger.info("Testcases generated from optional data provided",extra={'details':data_generated_through_LLM_from_optional_data})
    logger.info("Testcases generated from optional data provided")
    return(data_generated_through_LLM) 