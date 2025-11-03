import os
import json
import logging
logger = logging.getLogger('toolops.validation.tool_analysis')
pwd = os.getcwd()

from toolops.validation.tool_analysis.tool_analysis_utils.analyse_events.error_processing import get_error_taxonomy_recommendations
from toolops.validation.tool_analysis.tool_analysis_utils.report_utils.report_processing import get_final_report


class ErrorAnalysis:
    def __init__(self,tool_name,agentic_framework,test_cases_with_tool_execution):
        self.tool_name = tool_name
        self.agentic_framework = agentic_framework
        self.test_cases_with_tool_execution = test_cases_with_tool_execution

    def get_tool_report(self,report_level='short'):
        logger.info("Started test case analysis",extra={'details': json.dumps({'tool':self.tool_name})})
        test_cases_with_error_taxonomy_recommendations=get_error_taxonomy_recommendations(self.tool_name,self.agentic_framework,self.test_cases_with_tool_execution)
        logger.info("Completed test case analysis",extra={'details': json.dumps({'tool':self.tool_name})})
        logger.info("Started report generation for tool",extra={'details': json.dumps({'tool':self.tool_name})})
        final_report=get_final_report(test_cases_with_error_taxonomy_recommendations,self.tool_name,report_level)
        logger.info("Successfully generated test case report for tool",extra={'details': json.dumps({'tool':self.tool_name})})
        return test_cases_with_error_taxonomy_recommendations,final_report

if __name__=="__main__":
    test_data_path = os.path.join(pwd,"testing","testing_input_data","test_case_execution")
    output_report_path = os.path.join(pwd,"testing","testing_output_data","test_case_execution")
    tool_name,report_level,llm_name,agentic_framework = 'getTickets','detailed','mistral-large','langgraph'
    test_cases_with_tool_execution=json.load(open(os.path.join(output_report_path,llm_name+"_test_cases_with_tool_execution.json")))
    error_analysis=ErrorAnalysis(tool_name,agentic_framework,test_cases_with_tool_execution)
    test_cases_with_error_taxonomy_recommendations,final_report = error_analysis.get_tool_report(report_level)
    with open(os.path.join(output_report_path,llm_name+'_test_cases_with_error_taxonomy_recommendations.json'),'w') as ter:
        json.dump(test_cases_with_error_taxonomy_recommendations,ter,indent=2)
    ter.close()
    with open(os.path.join(output_report_path,llm_name+'_final_test_report.json'),'w') as fr:
        json.dump(final_report,fr,indent=2)
    fr.close()
    print(final_report)
    

