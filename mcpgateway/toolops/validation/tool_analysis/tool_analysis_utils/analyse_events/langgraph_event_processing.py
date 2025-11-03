import os
import json
import logging
from collections import Counter
logger = logging.getLogger('toolops.validation.test_case_execution_utils.analyse_events.langgraph_event_processing')

def get_tool_name_args_from_event(first_event):
    identified_tool_name = ''
    tool_args = ''
    try:
        tool_event = json.loads(first_event.get("turn_event"))
        if 'agent' in tool_event:
            tool_calls=tool_event.get("agent").get("messages")[0].get("kwargs").get("additional_kwargs").get('tool_calls')
            identified_tool_name = tool_calls[0].get('function').get('name')
            tool_args = tool_calls[0].get('function').get('arguments')
    except Exception as e:
        logger.info('Problem in parsing the first agentic flow execution event due to incorrect format',
                     extra={'details': json.dumps({'first_event':first_event,'error':str(e)})})
        pass
    return identified_tool_name,tool_args

def get_mandatory_optional_parameters(test_scenarios):
    mandatory_params,all_params,temp_man_params,temp_all_params=[],[],[],[]
    try:
        for ts in test_scenarios:
            temp_man_params.extend(ts.get('mandatory_params'))
            input_params = [param_f.split("((")[0].strip() for param_f in ts.get("input").split("\n")]
            temp_all_params.extend(input_params)
        mandatory_params=list(set(temp_man_params))
        all_params=[pa for pa in list(set(temp_all_params)) if pa!='']
    except Exception as e:
        logger.info('Problem in getting mandatory parameters, list of all parameters due to issue in test scenarios',
                     extra={'details': str(e)})
        pass
    return mandatory_params,all_params

def get_param_type_in_tool_input(tool_inputs,param_):
    param_type = None
    if param_ in tool_inputs:
        if type(tool_inputs.get(param_)) == str:
            param_type = 'string'
        elif type(tool_inputs.get(param_)) == list:
            param_type = 'array'
        elif type(tool_inputs.get(param_)) == int:
            param_type = 'integer'
        elif type(tool_inputs.get(param_)) == float:
            param_type = 'number'
        elif type(tool_inputs.get(param_)) == dict:
            param_type = 'object'
    return param_type
        
def fix_param_type_variations(param_t): 
    if param_t == 'str':
        param_type = 'string'
    elif param_t == 'int':
        param_type = 'integer'
    elif 'list' in param_t:
        param_type = 'array'
    else:
        param_type = param_t
    return param_type

def get_tool_inputs_from_agent_schema(tool_args_dict,tool_inputs={}):
    try:
        for key in tool_args_dict:
            val = tool_args_dict[key]
            if not isinstance(val, dict):
                tool_inputs[key] = val
            else:
                get_tool_inputs_from_agent_schema(val,tool_inputs)
        return tool_inputs
    except:
        return {}

#####################################################################
### Checking different error types in agent execution events ########
#####################################################################

def check_parameter_type_mismatch(test_scenario,agentic_flow_events):
    error_taxonomy = ''
    parameter_type_mismatch_msg = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        tool_inputs = get_tool_inputs_from_agent_schema(json.loads(tool_args))
        test_case_tool_input = test_scenario.get('input')
        type_mismatches = []
        if test_case_tool_input is not None and test_case_tool_input != "":
            inputs_list = test_case_tool_input.split("\n")
            for inp_ in inputs_list:
                param_ = inp_.split("((")[0].strip()
                param_type = fix_param_type_variations(inp_.split("((")[-1].split("))")[0].strip())
                tool_input_param_type = get_param_type_in_tool_input(tool_inputs,param_)
                if param_type != tool_input_param_type and param_ != '':
                    type_mismatches.append({'parameter':param_,'expected_param_type':param_type,'tool_input_param_type':tool_input_param_type})
        if type_mismatches != []:
            error_taxonomy = 'Incorrect tool inputs - Parameter Type Mismatch\n'
            parameter_type_mismatch_msg = 'Check tool input parameter type mismatch for : '+str(type_mismatches)+" , *** please modify the tool input processing code accordingly ***\n"
    except Exception as e:
        logger.info('Problem in checking parameter type mismatch errors due to issue in test scenario',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,parameter_type_mismatch_msg

def check_parameter_value_mismatch(test_scenario,agentic_flow_events):
    error_taxonomy = ''
    parameter_value_mismatch_msg = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        tool_call_inputs = get_tool_inputs_from_agent_schema(json.loads(tool_args))
        test_case_tool_input = test_scenario.get('input')
        value_mismatches = []
        if test_case_tool_input is not None and test_case_tool_input != "":
            inputs_list = test_case_tool_input.split("\n")
            for inp_ in inputs_list:
                param_ = inp_.split("((")[0].strip()
                param_val = json.loads(json.dumps(inp_.split(":=")[-1])).strip()
                if param_ in tool_call_inputs:
                    tool_ip_par_val = str(tool_call_inputs[param_])
                    if str(param_val) != tool_ip_par_val and len(param_)>=1:
                        value_mismatches.append({'parameter':param_,'expected_param_value':param_val,'tool_input_param_value':tool_ip_par_val})                
        if value_mismatches != []:
            error_taxonomy = 'Incorrect tool inputs - Parameter Value Mismatch\n'
            parameter_value_mismatch_msg = 'Check tool input parameter value mismatch for : '+str(value_mismatches)+" , *** please provide parameter descriptions,examples in the tool defintion, for the agent to correctly identify parameter values\n"
    except Exception as e:
        logger.info('Problem in checking parameter value mismatch errors due to issue in test scenario, agentic flow events',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,parameter_value_mismatch_msg

def check_tool_payload(agentic_flow_events,mandatory_params,all_params):
    payload_check_msg = ''
    final_payload_msg = ''
    error_taxonomy = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        tool_inputs = get_tool_inputs_from_agent_schema(json.loads(tool_args))
        if tool_inputs != {}:
            if mandatory_params != []:
                mis_man_params = []
                for mp in mandatory_params:
                    if mp not in tool_inputs:
                        mis_man_params.append(mp)
                if mis_man_params != []:
                    payload_check_msg += " Missing mandatory parameters - "+str(mis_man_params)        
            if all_params != []:
                in_correct_params = []
                for ti in tool_inputs:
                    if ti not in all_params:
                        in_correct_params.append(ti)
                if in_correct_params != []:
                    payload_check_msg += " Incorrect tool parameters - "+str(in_correct_params)
        if payload_check_msg != '':
            error_taxonomy = 'Incorrect tool input payload\n'
            final_payload_msg = 'Check tool input payload for : '+payload_check_msg+", *** please modify tool input processing code accordingly, provide parameter descriptions in the tool defintion for the agent to correctly identify parameters ***\n"
    except Exception as e:
        logger.info('Problem in checking tool input payload errors due to issue in agentic flow events, parameter list',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,final_payload_msg


def check_agent_tool_invocation_error(agentic_flow_events):
    error_taxonomy = ''
    agent_tool_invocation_error = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        # tool is identified by agent but tool args and tool invocation are not working
        if identified_tool_name != '' and len(agentic_flow_events) == 1:
            error_taxonomy = 'Agent tool calling issue\n'
            agent_tool_invocation_error = 'Agent could not invoke tool calling for the identified tool - '+identified_tool_name+' , *** please check the tool definition ***\n'
    except Exception as e:
        logger.info('Problem in checking agent tool calling error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,agent_tool_invocation_error

def check_agent_tool_inputs_issue(agentic_flow_events,tool_input_format=None):
    agent_tool_inputs_error = ''
    error_taxonomy = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        try:
            # to validate tool input args from agent , load it as a valid json
            tool_inputs = json.loads(tool_args)
            if tool_input_format is not None:
                # add code to compare tool input format schema with received tool inputs
                pass
        except:
            error_taxonomy = 'Agent tool calling issue - Incorrect Tool Input format\n'
            agent_tool_inputs_error = 'Agent could not invoke tool calling for the identified tool - '+identified_tool_name+' due to malformed tool input payload format , *** please modify the tool input processing code *** \n'
            pass
    except Exception as e:
        logger.info('Problem in checking agent tool input format error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,agent_tool_inputs_error

def check_recursive_tool_calling(agentic_flow_events,repetition_threshold=2):
    error_taxonomy = ''
    tools_called = []
    repeated_tool_calling = ''
    try:
        for ae in agentic_flow_events:
            tool_name,tool_args = get_tool_name_args_from_event(ae)
            if tool_name != '':
                tools_called.append(tool_name)
        tool_call_counter = dict(Counter(tools_called))
        max_tool_cal_count = max(tool_call_counter.values())
        if max_tool_cal_count >= repetition_threshold:
            error_taxonomy = 'Agent Recursive Tool Calling\n'
            repeated_tool_calling = 'Agent invoked the tool repeatedly several times, tools invoked - '+str(tool_call_counter)+', *** please modify the output returned in the tool definition accordingly, such that agent will not invoke the tool recursively ***\n'                     
    except Exception as e:
        logger.info('Problem in checking agent recursive tool calling error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,repeated_tool_calling

def check_llm_parsing_error(agentic_flow_events,tool_output_format=None):
    llm_parse_error = ''
    error_taxonomy = ''
    try:
        last_event = agentic_flow_events[-1]
        if "Could not parse LLM output" in json.dumps(last_event):
            if tool_output_format is not None:
                pass
            error_taxonomy = 'Tool Output parsing error\n'
            llm_parse_error = 'Could not parse the tool output, *** please check output returned in tool definition ***\n'
    except Exception as e:
        logger.info('Problem in checking llm parsing error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,llm_parse_error

def check_llm_token_limit_error(agentic_flow_events):
    llm_token_limit_error = ''
    error_taxonomy = ''
    try:
        last_event = agentic_flow_events[-1]
        if "cannot exceed the total tokens limit" in json.dumps(last_event):
            error_taxonomy = 'Tool Output exceeding LLM token limit\n'
            llm_token_limit_error = 'Agent LLM exceeding token limit, *** please try with a different LLM with large token limit *** \n'
    except Exception as e:
        logger.info('Problem in checking llm token limit error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,llm_token_limit_error

def check_correct_tool_identification(api_tool_name,agentic_flow_events):
    tool_identification_error = ''
    error_taxonomy = ''
    try:
        identified_tool_name,tool_args = get_tool_name_args_from_event(agentic_flow_events[0])
        if api_tool_name != identified_tool_name:
            error_taxonomy = 'Incorrect tool identification\n'
            tool_identification_error = 'Agent identified incorrect tool - expected tool : '+api_tool_name+', identified tool'+identified_tool_name+", *** please modify or add the tool descriptions accordingly ***\n"
    except Exception as e:
        logger.info('Problem in checking correct tool identification error due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy,tool_identification_error


def get_tool_final_output(agentic_flow_events):
    tool_final_output= {}
    tool_execution_status = ''
    try:
        final_act_event_output = None
        for ae in agentic_flow_events:
            if 'turn_event' in ae:
                tool_event = json.loads(ae.get("turn_event"))
                if "tools" in tool_event:
                    final_act_event_output = tool_event.get("tools").get("messages")[0].get('kwargs').get('content')
                    tool_execution_status = tool_event.get("tools").get("messages")[0].get('kwargs').get('status')
        tool_final_output = json.loads(final_act_event_output)
    except Exception as e:
        logger.info('Problem in obtaining tool final output due to issue in agentic flow events ',
                     extra={'details': str(e)})
        pass
    return tool_final_output,tool_execution_status


def check_tool_api_errors(test_scenario,agentic_flow_events):
    '''
    Method to identify tool API related errors such as Auth 401 error, 403 error etc and Server error, 500 error etc
    '''
    error_taxonomy = ''
    try:
        api_res_code = test_scenario.get('api_testing_output',{}).get('response_code',None)
        tool_final_output,tool_execution_status = get_tool_final_output(agentic_flow_events)
        if type(tool_final_output) == dict:
            tool_res_code = tool_final_output.get('status_code',None)
        else:
            tool_res_code = None
        # handling both api and tool response codes
        if api_res_code is not None:
            response_code = api_res_code
        elif api_res_code is None and tool_res_code is not None:
            response_code = tool_res_code
        else: 
            response_code = None
        # response code errors
        if response_code in [401,403]:
            error_taxonomy = 'Incorrect tool autorization or access credentials\n'
        elif response_code in [500,501,502,503,504]:
            error_taxonomy = 'Tool back-end server issue\n'  
        elif response_code in [400,422]:
            error_taxonomy = 'Issue with the inputs provided to the tool\n'
        elif response_code in [404]:
            error_taxonomy = 'No results found in the tool output\n'
        else:
            pass
    except Exception as e:
        logger.info('Problem in checking tool api errors due to issue in test scenario ',
                     extra={'details': str(e)})
        pass
    return error_taxonomy


def get_tool_test_case_status(test_scenario,agentic_flow_events,taxonomy): 
    test_status , tool_res_code = 'Not Available' , None
    api_res_code = test_scenario.get('api_testing_output',{}).get('response_code',None)
    tool_final_output,tool_execution_status = get_tool_final_output(agentic_flow_events)
    if type(tool_final_output) == dict:
        tool_res_code = tool_final_output.get('status_code',None)
    if taxonomy != '' :
        test_status = 'Failed'
    elif taxonomy == '' and tool_res_code is None:
        test_status = 'Not Available'
    elif taxonomy == '' and tool_res_code in [200,201]:
        test_status = 'Passed'
    elif taxonomy == '' and tool_res_code is not None and tool_res_code not in [200,201]:
        test_status = 'Failed'
    return test_status           

def identify_error_taxonomy(test_cases_with_tool_execution):
    '''
    This method processes different error taxonomy types : 
    --------------------------------
    1) In correct tool identification
    2) In correct payload - parameters missing
    3) In correct payload - parameter type mismatch
    4) Tool output parsing error (framework specific , actual API calling output is good)
    5) Tool output LLM token limit error
    6) Bad tool output response (react agent executes in iterative fashion with single tool calling multiple times)
    7) Agent tool invocation issue
    8) Agent tool invocation - incorrect tool input
    9) Correct tool calling with proper payload and desired tool output response
    '''
    test_scenarios = test_cases_with_tool_execution.get("Test_scenarios")
    mandatory_params , all_params = get_mandatory_optional_parameters(test_scenarios)
    for test_scenario in test_scenarios:
        api_tool_name = test_scenario.get("api_tool_name")
        ts_taxonomy_list = []
        ts_recommendations_list = []
        ts_status_list = []
        ts_nl_utterances = test_scenario.get('nl_utterance')
        tool_execution_responses = test_scenario.get('tool_execution_responses')
        if ts_nl_utterances is not None and ts_nl_utterances != ['']:
            for nl_utterance, tool_output in zip(ts_nl_utterances, tool_execution_responses):
                agentic_flow_events = tool_output.get('agentic_flow_events')
                taxonomy = ''
                recommendations = ''
                
                # checking incorrect tool identification errors
                logger.info("checking incorrect tool identification errors",extra={'details': json.dumps({'tool':api_tool_name})})
                tool_identification_taxonomy,tool_identification_check_msg = check_correct_tool_identification(api_tool_name,agentic_flow_events)
                if tool_identification_check_msg != '':
                    taxonomy += tool_identification_taxonomy
                    recommendations += tool_identification_check_msg

                # checking agent tool invocation issues
                logger.info("checking agent tool invocation issues",extra={'details': json.dumps({'tool':api_tool_name})})
                agent_tool_invocation_taxonomy,agent_tool_invocation_check_msg = check_agent_tool_invocation_error(agentic_flow_events)
                if agent_tool_invocation_check_msg != '':
                    taxonomy += agent_tool_invocation_taxonomy
                    recommendations += agent_tool_invocation_check_msg

                # checking agent tool invocation with incorrect tool inputs
                logger.info("checking agent tool invocation with incorrect tool inputs",extra={'details': json.dumps({'tool':api_tool_name})})
                agent_tool_inputs_taxonomy,agent_tool_inputs_check_msg = check_agent_tool_inputs_issue(agentic_flow_events)
                if agent_tool_invocation_check_msg != '':
                    taxonomy += agent_tool_inputs_taxonomy
                    recommendations += agent_tool_inputs_check_msg
                
                # checking tool backend server errors
                logger.info("checking tool server api errors",extra={'details': json.dumps({'tool':api_tool_name})})
                tool_api_taxonomy = check_tool_api_errors(test_scenario,agentic_flow_events)
                if tool_api_taxonomy != '':
                    taxonomy += tool_api_taxonomy
                    

                # checking incorrect tool payload with mandatory params and un-necessary parameters
                logger.info("checking incorrect tool payload with mandatory params and un-necessary parameters",extra={'details': json.dumps({'tool':api_tool_name})})
                tool_payload_taxonomy, tool_payload_check_msg = check_tool_payload(agentic_flow_events,mandatory_params,all_params)
                if tool_payload_check_msg != '':
                    taxonomy += tool_payload_taxonomy
                    recommendations += tool_payload_check_msg

                # checking tool parameter type mismatch errors
                logger.info("checking tool parameter type mismatch errors",extra={'details': json.dumps({'tool':api_tool_name})})
                tool_payload_param_type_taxonomy,tool_payload_param_type_check_msg = check_parameter_type_mismatch(test_scenario,agentic_flow_events)
                if tool_payload_param_type_check_msg != '':
                    taxonomy += tool_payload_param_type_taxonomy
                    recommendations += tool_payload_param_type_check_msg

                # checking tool parameter value mismatch errors
                logger.info("checking tool parameter value mismatch errors",extra={'details': json.dumps({'tool':api_tool_name})})
                tool_payload_param_value_taxonomy,tool_payload_param_value_check_msg = check_parameter_value_mismatch(test_scenario,agentic_flow_events)
                if tool_payload_param_value_check_msg != '':
                    taxonomy += tool_payload_param_value_taxonomy
                    recommendations += tool_payload_param_value_check_msg

                # checking recursive tool calling
                logger.info("checking recursive tool calling",extra={'details': json.dumps({'tool':api_tool_name})})
                recursive_tool_taxonomy,recursive_tool_calling = check_recursive_tool_calling(agentic_flow_events)
                if recursive_tool_calling != '':
                    taxonomy += recursive_tool_taxonomy
                    recommendations += recursive_tool_calling

                # checking LLM parsing error
                logger.info("checking LLM parsing error",extra={'details': json.dumps({'tool':api_tool_name})})
                llm_parse_taxonomy,llm_parse_error = check_llm_parsing_error(agentic_flow_events)
                if llm_parse_error != '':
                    taxonomy += llm_parse_taxonomy
                    recommendations += llm_parse_error

                # checking token limit error
                logger.info("checking token limit error",extra={'details': json.dumps({'tool':api_tool_name})})
                llm_token_limit_taxonomy,llm_token_limit_error = check_llm_token_limit_error(agentic_flow_events)
                if llm_token_limit_error != '':
                    taxonomy += llm_token_limit_taxonomy
                    recommendations += llm_token_limit_error

                ts_taxonomy_list.append(taxonomy)
                ts_recommendations_list.append(recommendations)
                ts_status = get_tool_test_case_status(test_scenario,agentic_flow_events,taxonomy)
                ts_status_list.append(ts_status)
        test_scenario['error_taxonomy_list']=ts_taxonomy_list
        test_scenario['error_recommendations_list']=ts_recommendations_list
        test_scenario['test_status_list']=ts_status_list
    return test_cases_with_tool_execution

# if __name__=='__main__':
#     pwd = os.getcwd()
#     #test_report_file_path = os.path.join(pwd,"testing","testing_output_data","test_case_execution","test_cases_with_tool_execution.json")
#     test_report_file_path = os.path.join(pwd,"testing","testing_output_data","full_pipeline","github_createissue","test_cases_with_tool_execution_events.json")
#     test_scenarios = json.load(open(test_report_file_path))
#     #print(test_scenarios)
#     #validation_report = tool_verification_report.get('validation_report')
#     #test_scenarios = validation_report.get('Test_scenarios')
#     test_scenarios_with_taxonomy = identify_error_taxonomy(test_scenarios)
#     #print(test_scenarios_with_taxonomy)
#     print([(ts.get('error_taxonomy_list'),ts.get('error_recommendations_list')) for ts in test_scenarios_with_taxonomy.get('Test_scenarios')])


