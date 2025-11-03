import json
import logging 
import sys
import os

logger = logging.getLogger('toolops.validation.test_case_generation_utils.utils.tool_spec_post_process')
parent_dir = os.path.dirname(os.path.join(os.getcwd(),"src"))
sys.path.append(parent_dir)

def tool_spec_post_process(tool_spec):
    tool_spec_json = json.loads(json.dumps(tool_spec))
    processed_json = dict()
    try:
        processed_json["operationid"] = tool_spec_json["name"]
        processed_json["description"] = tool_spec_json["description"]
        processed_json["operation"] = dict()
        if "python" in tool_spec_json["binding"]:
            processed_json["operation"][tool_spec_json["binding"]["python"]["function"]]=dict()
            for element in tool_spec_json["input_schema"]["properties"]:
                required_flag = "False"
                if element in tool_spec_json["input_schema"]["required"]:
                    required_flag = "True"
                title=""
                type="Not Specified"
                if "description" in tool_spec_json["input_schema"]["properties"][element]:
                    title = tool_spec_json["input_schema"]["properties"][element]["description"]
                if "type" in tool_spec_json["input_schema"]["properties"][element]:
                    type = tool_spec_json["input_schema"]["properties"][element]["type"]
                processed_json["operation"][tool_spec_json["binding"]["python"]["function"]][element] = {
                    "enum": "NA",
                    "format": [],
                    "required": required_flag,
                    "title": title,
                    "type": type,
                    "x-ibm-show": ""
                }
        else:    
            processed_json["operation"][tool_spec_json["binding"]["openapi"]["http_method"]] = dict()
            for param_type in  ["path_params", "request_body_params", "query_params", "header_params"]:
                processed_json["operation"][tool_spec_json["binding"]["openapi"]["http_method"]][param_type] = dict()    
            if "properties" in tool_spec_json["input_schema"]: 
                for element in tool_spec_json["input_schema"]["properties"]:
                    input_type = tool_spec_json["input_schema"]["properties"][element]["in"]
                    if input_type != "header":
                        input_type = input_type.replace("-", "_")+"_params"
                        required_flag = "False"
                        if element in tool_spec_json["input_schema"]["required"]:
                            required_flag = "True"
                        title=""
                        type="Not Specified"
                        if "description" in tool_spec_json["input_schema"]["properties"][element]:
                            title = tool_spec_json["input_schema"]["properties"][element]["description"]
                        if "type" in tool_spec_json["input_schema"]["properties"][element]:
                            type = tool_spec_json["input_schema"]["properties"][element]["type"]
                        processed_json["operation"][tool_spec_json["binding"]["openapi"]["http_method"]][input_type][element] = {
                            "enum": "NA",
                            "format": [],
                            "required": required_flag,
                            "title": title,
                            "type": type,
                            "x-ibm-show": ""
                        }
                        
            if "__requestBody__" in tool_spec_json["input_schema"] and "properties" in tool_spec_json["input_schema"]["__requestBody__"]:
                for element in tool_spec_json["input_schema"]["__requestBody__"]["properties"]:
                    input_type = "request-body"
                    input_type = input_type.replace("-", "_")+"_params"
                    example = "NA"
                    if "example" in tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]:
                        example = tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]["example"]
                    required_flag = "False"
                    if "required" in tool_spec_json["input_schema"]["__requestBody__"]: 
                        if element in tool_spec_json["input_schema"]["__requestBody__"]["required"]:
                            required_flag = "True"
                    elif "required" in tool_spec_json["input_schema"]:
                        if "__requestBody__" in tool_spec_json["input_schema"]["required"]:
                            required_flag = "True"
                    title = ""
                    type = "Not Specified"
                    if "type" in tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]:
                        type = tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]["type"]
                    if "description" in tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]:
                        title = tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]["description"]
                    elif "title" in tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]:
                        title = tool_spec_json["input_schema"]["__requestBody__"]["properties"][element]["title"]
                    processed_json["operation"][tool_spec_json["binding"]["openapi"]["http_method"]][input_type][element] = {
                        "enum": "NA",
                        "example": example,
                        "format": [],
                        "required": required_flag,
                        "title": title,
                        "type": type,
                        "x-ibm-show": ""
                    }
    except:
        pass
    return processed_json, tool_spec_json

def check_for_duplicate(specific_testcase, created_testcases_so_far):
    duplicate=False
    for testcase_index in created_testcases_so_far:
        if created_testcases_so_far[testcase_index] == specific_testcase:
            duplicate=True
            break
    return(duplicate)

def generated_testcase_to_nl_template(testcase):
    final_param = dict()
    for param in testcase:
        param_clean = param.replace(".array_item.", ".")
        param_clean = param_clean.replace(".array_item", ".")
        param_clean = param_clean.replace(".array.", ".")
        final_param[param_clean]=[testcase[param]]
    return(final_param)