import json
from langgraph.prebuilt import create_react_agent
import logging
logger = logging.getLogger('toolops.validation.test_case_execution_utils.agentenv.fr_langgraph.create_agents')

from toolops.utils.llm_util import get_agent_llm
from toolops.exceptions import AgentCreationError,AgentLLMConfigurationError

def get_agent(tools,tool_names,agent_llm,agent_type):
    if agent_type == 'react':
        try:
            logger.info('Running langgraph react agent creation with tools ', extra={'details': json.dumps({'agent_type':agent_type,
                                                                                       'tools':tool_names})})
            react_agent_with_tools = create_react_agent(agent_llm, tools)
            logger.info('Langgraph react agent with tools is created successfully', extra={'details': json.dumps({'agent_type':agent_type,
                                                                                       'tools':tool_names})})
            return react_agent_with_tools
        except Exception as e:
            logger.error('Errror in creating langgraph react agent with tools', extra={'details': json.dumps({'agent_type':agent_type,
                                                                                       'tools':tool_names})})
            raise AgentCreationError(agent_type,str(e))
    else:
        raise AgentCreationError(agent_type,"Agent type is not supported, please use correct agent type")


def get_tools_agent_flow(list_of_tools,tool_names,agent_llm_model_id,agent_type,llm_platform):
    agent_llm = get_agent_llm(agent_llm_model_id,agent_type,llm_platform)
    agent_with_tools = get_agent(list_of_tools,tool_names,agent_llm,agent_type)
    return agent_with_tools