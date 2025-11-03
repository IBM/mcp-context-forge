import os
import json
import importlib.util
import logging
logger = logging.getLogger('toolops.validation.test_case_execution_utils.agentenv.fr_langgraph.create_tools')

from toolops.exceptions import ToolCreationError

pwd = os.getcwd()

def get_tools(tool_details):
    '''
    Main method to create tools from API spec and return the langraph tool list
    tool_details : list of tool objects , with tool object containing tool name and tool definition as string
    example : [{'tool_name':'abc','tool_def_str':'xxxx'},{'tool_name':'xyz','tool_def_str':'abcd'}]
    '''
    tool_names,tool_list = [],[]
    try:
        logger.info('Obtaining required tools for the agentic environment', extra={'details': 'None'})
        for tool_obj in tool_details:
            tool_name, tool_def_str = tool_obj.get('tool_name'), tool_obj.get('tool_def_str')
            if tool_name is not None and tool_def_str is not None:
                spec = importlib.util.spec_from_loader('tool_py', loader=None)
                tool_py = importlib.util.module_from_spec(spec)
                exec(tool_def_str, tool_py.__dict__)
                tool_list.append(tool_py.__getattribute__(tool_name))
                tool_names.append(tool_name)   
        if tool_list != []:
            logger.info('Agentic environment tools are obtained successfully', extra={'details': json.dumps({'tools':tool_names})})
        else:
            logger.info('No tools are obtained for the agentic environment', extra={'details': json.dumps({'tools':tool_names})})
        return tool_names,tool_list
    except Exception as e:
        logger.error('Error in obtaining tool for the agentic environment',extra={'details': json.dumps({'tool_name':tool_name})})
        raise ToolCreationError(tool_name,str(e))