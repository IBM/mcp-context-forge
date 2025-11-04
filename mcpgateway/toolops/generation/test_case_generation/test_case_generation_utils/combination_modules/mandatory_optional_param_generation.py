import os
import sys
import json
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.prompt_execution import data_using_LLM, post_process_testcase

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# This method generates testcases using all mandatory paramteres and a combination of subset of optional parameters #
def mandatory_optional_param_testcase(transformed_tool_spec, data_generated_through_LLM, number_testcases_to_generate_more, original_number_of_testcases_to_generate_more, count_testcases, llm_model_id, llm_platform):
    data_generated_through_LLM_with_mandatory_and_some_optional_param=dict()
    correct_number_of_testcases_generated = False
    total_tries_made_to_generate_testcase = 0
    while (number_testcases_to_generate_more > 0):
        total_tries_made_to_generate_testcase=total_tries_made_to_generate_testcase+1
        if (total_tries_made_to_generate_testcase==11):
            break
        incorrectly_generated_data=True
        count_failed_execution=0
        data_generated_through_LLM_so_far = dict()
        while(incorrectly_generated_data):
            try:
                prompt = """Generate """+str(number_testcases_to_generate_more)+""" diverse testcases with different but valid combination of optional parameters and all the mandatory parameters for the following spec where for each testcase provide the parameter and the corresponding realistic value without the word 'example'in it. If "example" values are given for a parameter then only use those values in testcases for the parameter. Do not use any parameter named "extra_param" if it is not in the specification. Do not use "None" as a value for parameter. The generated text should be in a dictionary format such as {“testcase_#number”: {“parameter 1”: “value 1”, “parameter 2”: “value 2”, ...}.\n"""+json.dumps(transformed_tool_spec)+"""\n"""
                data_generated_through_LLM_so_far = post_process_testcase(data_using_LLM(prompt, llm_model_id, llm_platform))
                incorrectly_generated_data=False
                for case in data_generated_through_LLM_so_far:
                    count_testcases=count_testcases+1
                    data_generated_through_LLM["testcase_"+str(count_testcases)] = data_generated_through_LLM_so_far[case]
                    data_generated_through_LLM_with_mandatory_and_some_optional_param["testcase_"+str(count_testcases)] = data_generated_through_LLM_so_far[case]
                    if count_testcases == original_number_of_testcases_to_generate_more:
                        correct_number_of_testcases_generated=True
                        break
                number_testcases_to_generate_more = original_number_of_testcases_to_generate_more - count_testcases
                if (correct_number_of_testcases_generated==True):
                    break
            except Exception as e:
                logger.info("Error in generating test cases for - mandatory and some optional"+str(e))
                count_failed_execution=count_failed_execution+1
                if count_failed_execution==3:
                    break
                incorrectly_generated_data=True
    #logger.info("Testcases generated with all mandatory and some optional parameters",extra={'details':data_generated_through_LLM_with_mandatory_and_some_optional_param})
    logger.info("Testcases generated with all mandatory and some optional parameters")
    return(data_generated_through_LLM)