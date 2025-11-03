'''
This module is for testing a tool in agentic environment
'''
import os
import json
import uuid
from langchain.load.dump import dumps as langchain_dumps
import logging
import json
from toolops.validation.test_case_execution.test_case_execution_utils.agentenv.fr_langgraph.tool_env import ToolAgenticEnv as agentic_langgraph_env,check_tool_details
from toolops.utils.llm_util import check_llm_env_vars
logger = logging.getLogger('toolops.validation.test_case_execution')
pwd = os.getcwd()


class ToolNLTestCaseExecution:
    def __init__(self,tool_details,agentic_framework='langgraph',
                 agent_llm_model_id='mistralai/mistral-medium-2505',agent_type='react',llm_platform='WATSONX'):
        self.tool_details = tool_details
        self.agentic_framework = agentic_framework
        self.agent_llm_model_id = agent_llm_model_id
        self.agent_type = agent_type
        self.llm_platform = llm_platform
        check_llm_env_vars(self.llm_platform)
        check_tool_details(self.tool_details)

    def tool_test_execution_report_with_llm_details(self,test_cases_report):
        tool_test_execution = {'tool_url':test_cases_report.get('Skill_operation','')}

        # adding llm models
        llm_model_dict = test_cases_report.get('llm_model_details',{})
        llm_model_dict['agent-model-id']=self.agent_llm_model_id
        tool_test_execution['llm_model_details']=llm_model_dict
        
        # adding llm platform
        llm_platform_dict = test_cases_report.get('llm_platform_details',{})
        llm_platform_dict['agent-llm-platform']=self.llm_platform
        tool_test_execution['llm_platform_details']=llm_platform_dict
        
        # adding tool details
        tool_test_execution['tool_details']=test_cases_report.get('tool_details',{})

        # adding agent details      
        tool_test_execution['agent_details']={'agentic_framework':self.agentic_framework,'agent_type':self.agent_type}

        return tool_test_execution

        
    def get_agent_env_with_tools(self):
        '''
        Method to set up agentic environment with given tools and agentic framework
        '''
        if self.agentic_framework == 'langgraph':
            agentic_flow_with_tools,tool_name = agentic_langgraph_env(self.tool_details,self.agent_llm_model_id,self.agent_type,self.llm_platform).get_tool_environment()
            logger.info("Agentic environment set up is complete for testing tools",extra={'details': json.dumps({'agent_type':self.agent_type,'tool':tool_name,'agentic_framework':self.agentic_framework})})
        else:
            pass
        return agentic_flow_with_tools,tool_name

    def run_tool_nl_test_cases(self,test_cases_report,agentic_flow_with_tools,tool_name):
        '''
        Method to execute tool test cases with NL utterances in agentic flow 
        '''
        if self.agentic_framework=='langgraph':
            tool_test_execution = self.tool_test_execution_report_with_llm_details(test_cases_report)
            test_cases = test_cases_report.get('Test_scenarios')
            test_cases_with_tool_execution = []
            agentic_flow = agentic_flow_with_tools
            logger.info("Started tool test cases execution",extra={'details': json.dumps({'tool':tool_name,'no_of_test_cases':len(test_cases),
                                                                                      'agentic_framework':self.agentic_framework,
                                                                                      'llm_platform':self.llm_platform,
                                                                                      'agent_llm_model_id':self.agent_llm_model_id})})
            for i,tc in enumerate(test_cases):
                logger.info("Executing test case : "+str(i+1),extra={'details': json.dumps({'tool':tool_name})})
                input_utterances = tc.get('nl_utterance')
                tool_execution_responses=[]
                for j,input_utterance in enumerate(input_utterances):
                    logger.info("Testing tool nl utterance : "+str(j+1),extra={'details': json.dumps({'tool':tool_name,'nl_utterance':input_utterance})})
                    thread_id = "thread_id_"+uuid.uuid4().hex
                    config = {"configurable": {"thread_id": thread_id}}
                    all_events = []
                    logger.info("Agent flow execution events ",extra={'details': json.dumps({})})
                    try:
                        for i,event in enumerate(agentic_flow.stream({"messages": [("user", input_utterance)]}, config, stream_mode="updates")):
                            turn_id = "turn_id_"+str(i+1)
                            turn_event = {'turn_id': turn_id,"turn_event":langchain_dumps(event)}
                            all_events.append(turn_event)
                            logger.info("Agent execution turn event",extra={'details': json.dumps(turn_event)})
                    except Exception as e:
                        logger.error("Exception occured in running agentic flow , "+str(e),extra={'details': json.dumps({'tool':tool_name,'nl_utterance':input_utterance})})
                        pass
                    tool_response = {'utterance':input_utterance,'agentic_flow_events':all_events}
                    tool_execution_responses.append(tool_response)
                tc['tool_execution_responses']=tool_execution_responses
                tc['tool_name']=tool_name
                test_cases_with_tool_execution.append(tc)
            tool_test_execution['Test_scenarios']=test_cases_with_tool_execution
            logger.info("Completed tool test cases execution",extra={'details': json.dumps({'tool':tool_name,'no_of_test_cases':len(test_cases)})})
        else:
            logger.info("Invalid agentic framework is provided, could not run tool test cases",extra={'details': json.dumps({'tool':tool_name,
                                                                                      'agentic_framework':self.agentic_framework,
                                                                                      'llm_platform':self.llm_platform,
                                                                                      'agent_llm_model_id':self.agent_llm_model_id})})
            tool_test_execution = test_cases_report
        return tool_test_execution



if __name__=="__main__":
    test_data_path = os.path.join(pwd,"testing","testing_input_data","test_case_execution")
    output_report_path = os.path.join(pwd,"testing","testing_output_data","test_case_execution")
    test_tool_def_str = open(os.path.join(test_data_path,'getApiV2Tickets_tool.py')).read()
    tool_details = [{'tool_name':'getApiV2Tickets','tool_def_str':test_tool_def_str}]
    test_case_report = json.load(open(os.path.join(test_data_path,"getApiV2Tickets_nltestcases.json"),'r'))
    # 'meta-llama/llama-3-405b-instruct',"mistralai/mistral-medium-2505", meta-llama/llama-3-3-70b-instruct ,meta-llama/llama-3-1-405b-instruct-fp8 , meta-llama/llama-4-maverick-17b-128e-instruct-fp8
    agentic_framework,agent_llm_model_id,agent_type,llm_platform='langgraph',"mistralai/mistral-medium-2505","react","WATSONX"
    tool_nl_tc_execution = ToolNLTestCaseExecution(tool_details,agentic_framework,agent_llm_model_id,agent_type,llm_platform)
    agentic_flow_with_tools,tool_name = tool_nl_tc_execution.get_agent_env_with_tools()
    print(agentic_flow_with_tools,tool_name)
    test_cases_with_tool_execution = tool_nl_tc_execution.run_tool_nl_test_cases(test_case_report,agentic_flow_with_tools,tool_name)
    with open(os.path.join(output_report_path,agent_llm_model_id.split("/")[-1]+'_test_cases_with_tool_execution.json'),'w') as ttr:
        json.dump(test_cases_with_tool_execution,ttr,indent=2)
    ttr.close()
    print(test_cases_with_tool_execution)