from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.utils import generated_testcase_to_nl_template

def all_testcase_postprocess(positive_testcases, negative_testcases, transformed_tool_spec, original_tool_spec, llm_model_id, llm_platform):
    number_of_mandatory_parameters_covered=0
    total_param_covered_number=0
    number_of_optional_parameters_covered=0
    number_of_positive_test_scenarios=0
    final_report=dict()
    required_keys = []
    operation_type = list(transformed_tool_spec["operation"].keys())[0]
    if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
        for param_type in ["request_body_params", "query_params", "path_params"]: 
            for key in transformed_tool_spec["operation"][operation_type][param_type]:
                if transformed_tool_spec["operation"][operation_type][param_type][key]["required"] == "True":
                    required_keys.append(key)
    else:
        for key in transformed_tool_spec["operation"][operation_type]:
            if transformed_tool_spec["operation"][operation_type][key]["required"] == "True":
                required_keys.append(key)

    total_param_covered = set()
    if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
        common_keys = set(transformed_tool_spec["operation"][operation_type].keys()).intersection(set(["path_prams", "query_params", "request_body_params"]))
        overlapping_params = set()
        for cm_key in common_keys:
            if cm_key == "query_params" or cm_key == "path_params":
                overlapping_params=overlapping_params.union(set(transformed_tool_spec["operation"][operation_type][cm_key].keys()))
        if "request_body_params" in list(transformed_tool_spec["operation"][operation_type].keys()):
            overlapping_params = overlapping_params.intersection(
                transformed_tool_spec["operation"][operation_type]["request_body_params"].keys()    
                )
        else:
            overlapping_params = set()
    for testcase_index in positive_testcases:
        testcase = positive_testcases[testcase_index]
        total_param_covered = total_param_covered.union(set(testcase.keys()))
        if "__requestBody__" in total_param_covered:
            total_param_covered_number=len(total_param_covered)-1
        else:
            total_param_covered_number=len(total_param_covered)
    mandatory_parameters_initial = set(required_keys).intersection(total_param_covered)
    number_of_mandatory_parameters_covered = len(mandatory_parameters_initial)
    number_of_mandatory_parameters_covered_in_request_body_list=[]
    number_of_total_parameters_covered_in_request_body_list=[]
    for testcase_index in positive_testcases:
        testcase = positive_testcases[testcase_index]
        if "__requestBody__" in testcase:
            for param in testcase["__requestBody__"]:
                if param in transformed_tool_spec["operation"][operation_type]["request_body_params"]:
                    if transformed_tool_spec["operation"][operation_type]["request_body_params"][param]["required"]=="True":
                        if param not in overlapping_params:
                            if param not in mandatory_parameters_initial and param not in number_of_mandatory_parameters_covered_in_request_body_list:
                                number_of_mandatory_parameters_covered_in_request_body_list.append(param)
                        else:
                            if param not in number_of_mandatory_parameters_covered_in_request_body_list:
                                number_of_mandatory_parameters_covered_in_request_body_list.append(param)
                    if param not in overlapping_params:
                        if param not in total_param_covered and param not in number_of_total_parameters_covered_in_request_body_list:
                            number_of_total_parameters_covered_in_request_body_list.append(param)
                    else:
                        if param not in number_of_total_parameters_covered_in_request_body_list:
                            number_of_total_parameters_covered_in_request_body_list.append(param)
    number_of_mandatory_parameters_covered=number_of_mandatory_parameters_covered+len(number_of_mandatory_parameters_covered_in_request_body_list)
    if "__requestBody__" in number_of_total_parameters_covered_in_request_body_list:
        total_param_covered_number = total_param_covered_number+len(number_of_total_parameters_covered_in_request_body_list)-1
    else:
        total_param_covered_number = total_param_covered_number+len(number_of_total_parameters_covered_in_request_body_list)
    number_of_optional_parameters_covered = total_param_covered_number - number_of_mandatory_parameters_covered
    number_of_positive_test_scenarios = len(positive_testcases)
    test_scenario=[]
    for testcase_index_outer in [positive_testcases, negative_testcases]:
        for testcase_index in testcase_index_outer:
            test_case_specific_details=dict()
            testcase = testcase_index_outer[testcase_index]
            test_case_specific_details["id"] = "TC_"+str(testcase_index)
            if testcase_index_outer is positive_testcases:
                test_case_specific_details["scenario_type"] = "positive"
            else:
                test_case_specific_details["scenario_type"] = "negative"
            if "__requestBody__" in list(testcase.keys()):
                test_case_specific_details["mandatory_params"] = list(set(testcase.keys()).intersection(set(required_keys)))+list(set(number_of_mandatory_parameters_covered_in_request_body_list).intersection(set(testcase["__requestBody__"].keys())))
            else:
                test_case_specific_details["mandatory_params"] = list(set(testcase.keys()).intersection(set(required_keys)))
            input_string=""
            for param in testcase:
                param_type_val = "string"
                key=param
                value = testcase[param]
                param_found_flag=False
                if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
                    for param_type in ["request_body_params", "query_params", "path_params"]: 
                        for specific_param in transformed_tool_spec["operation"][operation_type][param_type]:
                            if key == specific_param:
                                param_type_val = transformed_tool_spec["operation"][operation_type][param_type][specific_param]["type"]
                                param_found_flag=True
                                break
                        if param_found_flag==True:
                            break
                    if key != "__requestBody__" and param_found_flag==True:
                        input_string = input_string+str(key)+"(("+str(param_type_val)+")) := "+str(value)+" \n"
                    if key == "__requestBody__":
                        for parameters in testcase["__requestBody__"]:
                            param_type_val = "string"
                            value = testcase["__requestBody__"][parameters]
                            param_found_flag=False
                            for param_type in ["request_body_params"]:
                                for specific_param in transformed_tool_spec["operation"][operation_type][param_type]:
                                    if parameters == specific_param:
                                        param_type_val = transformed_tool_spec["operation"][operation_type][param_type][specific_param]["type"]
                                        param_found_flag=True
                                        break
                                if param_found_flag==True:
                                    break
                            if (param_found_flag==True):
                                input_string = input_string+str(parameters)+"(("+str(param_type_val)+")) := "+str(value)+" \n"
                else:
                    for specific_param in transformed_tool_spec["operation"][operation_type]:
                        if key == specific_param:
                            param_type_val = transformed_tool_spec["operation"][operation_type][specific_param]["type"]
                            input_string = input_string+str(key)+"(("+str(param_type_val)+")) := "+str(value)+" \n"
                            break
            test_case_specific_details["input"] = input_string
            test_case_specific_details["nl_utterance"] = [""]
            if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
                test_case_specific_details["input_parameters"] = generated_testcase_to_nl_template(testcase)
                test_scenario.append(test_case_specific_details)
            else:
                if testcase_index_outer is positive_testcases:
                    non_hallucinated_keys = set(generated_testcase_to_nl_template(testcase).keys()).intersection(set(transformed_tool_spec["operation"][operation_type].keys()))
                    test_case_specific_details["input_parameters"] = {k: generated_testcase_to_nl_template(testcase)[k] for k in non_hallucinated_keys}
                    if len(set(required_keys) - set(non_hallucinated_keys)) == 0:
                        test_scenario.append(test_case_specific_details)
                else:
                    non_hallucinated_keys = set(generated_testcase_to_nl_template(testcase).keys()).intersection(set(transformed_tool_spec["operation"][operation_type].keys()))
                    test_case_specific_details["input_parameters"] = {k: generated_testcase_to_nl_template(testcase)[k] for k in non_hallucinated_keys}
                    if len(set(non_hallucinated_keys) - set(required_keys)) == 0:
                        test_scenario.append(test_case_specific_details)
    final_report["Test_scenarios"] = test_scenario
    final_report["Number_of_mandatory_parameters_covered"] = number_of_mandatory_parameters_covered
    final_report["Number_of_optional_parameters_covered"] = number_of_optional_parameters_covered
    final_report["Number_of_positive_test_scenarios"] = number_of_positive_test_scenarios
    final_report["llm_model_details"] = dict()
    final_report["llm_model_details"]["tcg-model-id"] = llm_model_id
    final_report["llm_model_details"]["nlg-model-id"] = None
    final_report["llm_platform_details"] = dict()
    final_report["llm_platform_details"]["tcg-platform"] = llm_platform
    final_report["llm_platform_details"]["nlg-platform"] = None
    final_report["agent_details"] = dict()
    final_report["tool_details"] = dict()
    if "python" not in original_tool_spec["binding"]:
        final_report["Skill_operation"] = "API - "+original_tool_spec["binding"]["openapi"]["http_path"]+" , Operation - "+original_tool_spec["binding"]["openapi"]["http_method"]
    else:
        final_report["Skill_operation"] = "python -"+original_tool_spec["name"]+" , function - "+original_tool_spec["binding"]["python"]["function"]
    final_report["tool_definition"] = original_tool_spec
    return(final_report)