import logging
import json
logger = logging.getLogger('toolops.validation.test_case_execution_utils.analyse_events.error_processing')
from toolops.validation.tool_analysis.tool_analysis_utils.analyse_events.langgraph_event_processing import identify_error_taxonomy as langgraph_identify_error_taxonomy


def get_error_taxonomy_recommendations(tool_name,agentic_framework,test_cases_with_tool_execution):
    logger.info("Running error taxonomy and recommendations",extra={'details': json.dumps({'tool':tool_name,'agentic_framework':agentic_framework})})
    try:
        if agentic_framework == 'langgraph':
            logger.info("processing test case errors for langgraph framework",extra={'details': None})
            test_cases_with_error_taxonomy_recommendations = langgraph_identify_error_taxonomy(test_cases_with_tool_execution)
            return test_cases_with_error_taxonomy_recommendations
    except Exception as e:
        logger.info("Error in processing test case errors for "+agentic_framework+"framework hence could not complete full error analysis",extra={'details': str(e)})
        return test_cases_with_tool_execution
        
    
