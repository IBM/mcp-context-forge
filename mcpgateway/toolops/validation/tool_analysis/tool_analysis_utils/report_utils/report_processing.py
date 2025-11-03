import json
import os
import logging
logger = logging.getLogger('toolops.validation.test_case_execution_utils.tool_utils.report_processing')

def process_str_as_list(str_text):
    return [ele for ele in str_text.split("\n") if ele != ""]


def get_final_report(test_cases_with_error_taxonomy_recommendations,tool_name,report_level):
    '''
    Allowed report_levels : 'detailed' , 'short'
    '''
    logger.info("Processing the tool test cases report",extra={'details': json.dumps({'report_level':report_level})})           
    tool_test_cases = []
    test_scenarios = test_cases_with_error_taxonomy_recommendations.get('Test_scenarios')
    for test_scenario in test_scenarios:
        ts_nl_utterances = test_scenario.get('nl_utterance')
        tool_execution_responses = test_scenario.get('tool_execution_responses')
        tool_error_taxonomy = test_scenario.get('error_taxonomy_list')
        tool_error_recommendations = test_scenario.get('error_recommendations_list')
        tool_test_status_list= test_scenario.get('test_status_list')
        if ts_nl_utterances is not None and ts_nl_utterances != []:
            for nl_utterance,tool_output,error_taxonomy,error_recommendations,test_status in zip(ts_nl_utterances,tool_execution_responses,tool_error_taxonomy,tool_error_recommendations,tool_test_status_list):
                tool_ts_obj={}
                tool_ts_obj['test_utterance']=nl_utterance
                tool_ts_obj['tool_mandatory_inputs'] = test_scenario.get('mandatory_params')
                tool_ts_obj['tool_inputs']=test_scenario.get('input')
                tool_ts_obj['test_status']= test_status
                tool_ts_obj['test_error_taxonomy']= process_str_as_list(error_taxonomy)
                tool_ts_obj['test_error_recommendations']= process_str_as_list(error_recommendations)
                tool_ts_obj['tool_source_testing_output']= test_scenario.get('tool_source_testing_output',None)
                if report_level == 'detailed':
                    tool_ts_obj['tool_execution_events']= tool_output
                tool_test_cases.append(tool_ts_obj)
    tool_verification_final_report={
        'tool_url': test_cases_with_error_taxonomy_recommendations.get('tool_url'),
        'tool_name':tool_name,
        'tool_environment_details':{'agent_details':test_cases_with_error_taxonomy_recommendations.get('agent_details',{}),
                                    'llm_model_details':test_cases_with_error_taxonomy_recommendations.get('llm_model_details',{}),
                                    'llm_platform_details':test_cases_with_error_taxonomy_recommendations.get('llm_platform_details',{}),
                                    'tool_details':test_cases_with_error_taxonomy_recommendations.get('tool_details',{}),
                                    },
        'number_of_test_cases': len(tool_test_cases),
        'tool_test_cases':tool_test_cases
    }
    logger.info("Completed processing the tool test cases report",extra={'details': json.dumps({'report_level':report_level})})           
    return tool_verification_final_report

# if __name__=='__main__':
#     pwd = os.getcwd()
#     test_report_path = os.path.join(pwd,"testing","testing_output_data","full_pipeline","github_createissue","test_cases_with_error_recommendations_WATSONX_mistral-large.json")
#     test_cases_with_error_taxonomy_recommendations = json.load(open(test_report_path))
#     tool_name,report_level = 'github_createissue','detailed'
#     get_final_report(test_cases_with_error_taxonomy_recommendations,tool_name,report_level)







    