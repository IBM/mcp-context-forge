
import json
from toolops.validation.test_case_execution.test_case_execution_utils.agentenv.fr_langgraph.create_agents import get_tools_agent_flow
from toolops.validation.test_case_execution.test_case_execution_utils.agentenv.fr_langgraph.create_tools import get_tools
from toolops.exceptions import AgenticEnvCreationError,ToolDetailsError

import logging
logger = logging.getLogger('toolops.validation.test_case_execution_utils.agentenv.fr_langgraph.create_agents')

class ToolAgenticEnv:
    def __init__(self,tool_details,agent_llm_model_id='mistralai/mistral-medium-2505',agent_type='react',llm_platform='WATSONX'):
        self.tool_details = tool_details
        self.agent_llm_model_id = agent_llm_model_id
        self.agent_type = agent_type
        self.llm_platform = llm_platform
        self.tool_name = None
        self.tool_names = []
        self.tools = []

    def get_tool_environment(self):
        try:
            logger.info("Creating agentic environment",extra={'details': json.dumps({'agent_type':self.agent_type,
                                                                                     'llm_platform':self.llm_platform,
                                                                                     'agent_llm_model_id':self.agent_llm_model_id})})
            self.tool_names,self.tools = get_tools(self.tool_details)
            self.agentic_flow_with_tools = get_tools_agent_flow(self.tools,self.tool_names,self.agent_llm_model_id,self.agent_type,self.llm_platform)
            if len(self.tools) >= 1:
                self.tool_name = self.tools[0].name
            logger.info("Successfully created agentic environment",extra={'details': json.dumps({'agent_type':self.agent_type,
                                                                                       'tools':self.tool_names})})
            return self.agentic_flow_with_tools,self.tool_name
        except Exception as e:
            logger.error("Error in creating agentic environment",extra={'details': json.dumps({'agent_type':self.agent_type,
                                                                                               'llm_platform':self.llm_platform,
                                                                                                'agent_llm_model_id':self.agent_llm_model_id,
                                                                                                'tools':self.tool_names})})
            raise AgenticEnvCreationError(self.tool_name,self.agent_type,str(e))
        

def check_tool_details(tool_details):
    if tool_details is None or type(tool_details) != list or 'tool_name' not in tool_details[0] or 'tool_def_str' not in tool_details[0]:
        raise ToolDetailsError
    else:
        pass
