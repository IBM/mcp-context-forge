import json
import yaml
import os
import json
import sys
import copy
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.utils import tool_spec_post_process, check_for_duplicate
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.combination_modules.all_param_generation import all_param_testcase
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.combination_modules.mandatory_optional_param_generation import mandatory_optional_param_testcase
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.combination_modules.mandatory_param_generation import mandatory_param_testcase
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.using_optionally_provided_data.testcase_optional_data import generate_testcases_optional_data
from mcpgateway.toolops.generation.test_case_generation.test_case_generation_utils.all_testcase_post_process import all_testcase_postprocess

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class TestcaseGeneration:
    def __init__(self, llm_model_id, llm_platform, max_number_testcases_to_generate=10, no_test_data_generation=False, optional_data_scenario_path=None):
        self.llm_platform = llm_platform
        self.llm_model_id = llm_model_id
        self.max_number_testcases_to_generate = max_number_testcases_to_generate
        self.no_test_data_generation = no_test_data_generation
        self.optional_data_scenario_path = optional_data_scenario_path

    # This method generates postiive testcases 
    def positive_testcase_generation(self,transformed_tool_spec, original_tool_spec, optional_data_scenario):
        max_number_testcases_to_generate = self.max_number_testcases_to_generate
        created_testcase_from_optional_data = dict()
        test_case_lineage_from_optional_data = dict()
        created_testcase_with_zero_params = dict()
        test_case_lineage_with_zero_params = dict()
        test_case_lineage = dict()
        if optional_data_scenario != None:
            count=0
            created_data_so_far=dict()
            try:
                data_generated_through_LLM = generate_testcases_optional_data(transformed_tool_spec, optional_data_scenario, self.llm_model_id, self.llm_platform, max_number_testcases_to_generate)
            except:
                pass
            generated_testcase_keys = list(data_generated_through_LLM.keys())
            created_data = dict()
            test_case_lineage = dict()
            for testcase_index in generated_testcase_keys:
                specific_testcase = data_generated_through_LLM[testcase_index]
                duplicate_flag = check_for_duplicate(specific_testcase, created_data_so_far) 
                if duplicate_flag==False:
                    count=count+1
                    created_data_so_far[count] = specific_testcase
                    created_data[count] = specific_testcase
                    specific_testcase_lineage = dict()
                    data_generation_text="generated"
                    for key in created_data[count]:
                        key_found=False
                        for scenario in optional_data_scenario:
                            if key in list(scenario.keys()):
                                if scenario[key] == created_data[count][key]:
                                    data_generation_text="user given"
                                    key_found=True
                                    break
                            if key_found==True:
                                break
                        try:
                            specific_testcase_lineage[key] = {created_data[count][key]:data_generation_text}
                        except:
                            try:
                                specific_testcase_lineage[key] = {str(created_data[count][key]):data_generation_text}
                            except:
                                specific_testcase_lineage[key] = {"dummy":"generated"}
                    test_case_lineage["Testcase_"+str(count)] = specific_testcase_lineage
        else:
            count = len(created_testcase_from_optional_data)
            if (max_number_testcases_to_generate > count):
                required_keys = []
                operation_type = list(transformed_tool_spec["operation"].keys())[0]
                if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
                    for param_type in ["request_body_params", "query_params", "path_params"]: 
                        for key in transformed_tool_spec["operation"][operation_type][param_type]:
                            if transformed_tool_spec["operation"][operation_type][param_type][key]["required"] == "True":
                                required_keys.append(key)
                else:
                    for key in transformed_tool_spec["operation"][operation_type]:
                        try:
                            if transformed_tool_spec["operation"][operation_type][key]["required"] == "True":
                                required_keys.append(key)
                        except:
                            pass

                null_case_flag = False
                if len(required_keys) == 0:
                    null_case_flag = True
                if null_case_flag == True:
                    created_testcase_with_zero_params[count+1] = {}
                    duplicate_flag = check_for_duplicate(created_testcase_with_zero_params, created_testcase_from_optional_data) 
                    if duplicate_flag==False:
                        test_case_lineage_with_zero_params["Testcase_"+str(count+1)] = {}
                        count=count+1
                created_data_so_far = {**created_testcase_from_optional_data, **created_testcase_with_zero_params}
                if (max_number_testcases_to_generate > count):
                    number_testcases_to_generate_more = max_number_testcases_to_generate - count
                    created_testcases_full_from_LLM, test_case_lineage_full_from_LLM = self.generate_data_fully_using_LLM(original_tool_spec["input_schema"], number_testcases_to_generate_more, count, created_data_so_far, transformed_tool_spec)
            created_data = {**created_testcase_from_optional_data, **created_testcase_with_zero_params, **created_testcases_full_from_LLM}
            test_case_lineage = {**test_case_lineage_from_optional_data, **test_case_lineage_with_zero_params, **test_case_lineage_full_from_LLM}
        if (len(created_data) == max_number_testcases_to_generate):
            #logger.info("Test case generation complete. Successfully generated all the testcases",extra={'details':created_data})
            logger.info("Test case generation complete. Successfully generated all the testcases")
        return (created_data, test_case_lineage)

    # This method generates negative (invalid) testcases by omitting one mandatory parameter 
    def negative_testcase_generation(self, positive_testcases_generated, transformed_tool_spec):
        negative_testcases = dict()
        if len(positive_testcases_generated) > 0:
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

            one_positive_testcase = positive_testcases_generated[list(positive_testcases_generated.keys())[0]]
            if len(required_keys) > 0:
                count = len(positive_testcases_generated)
                for mand_params in required_keys:
                    temp_testcase = copy.deepcopy(one_positive_testcase)
                    try:
                        del temp_testcase[mand_params]
                    except:
                        try:
                            if "__requestBody__" in temp_testcase:
                                try:
                                    del temp_testcase["__requestBody__"][mand_params]
                                except:
                                    pass
                        except:
                            pass
                    count=count+1
                    negative_testcases[count] = temp_testcase
        return negative_testcases

    def generate_data_fully_using_LLM(self, transformed_tool_spec, number_testcases_to_generate_more, count, created_data_so_far, transformed_tool_spec_postprocess):
        data_generated_through_LLM=dict()
        original_number_of_testcases_to_generate_more = number_testcases_to_generate_more
        count_testcases=1
        if number_testcases_to_generate_more >=1:
            try:
                data_generated_through_LLM, number_testcases_to_generate_more = all_param_testcase(transformed_tool_spec, data_generated_through_LLM, number_testcases_to_generate_more, transformed_tool_spec_postprocess, self.llm_model_id, self.llm_platform)
            except:
                pass
        if number_testcases_to_generate_more >=1:
            try:
                data_generated_through_LLM, number_testcases_to_generate_more, count_testcases = mandatory_param_testcase(transformed_tool_spec_postprocess, data_generated_through_LLM, number_testcases_to_generate_more, count_testcases)        
            except:
                pass
        if number_testcases_to_generate_more >=1:
            try:
                data_generated_through_LLM = mandatory_optional_param_testcase(transformed_tool_spec, data_generated_through_LLM, number_testcases_to_generate_more, original_number_of_testcases_to_generate_more, count_testcases, self.llm_model_id, self.llm_platform)
            except:
                pass
        generated_testcase_keys = list(data_generated_through_LLM.keys())
        created_data = dict()
        test_case_lineage = dict()
        for testcase_index in generated_testcase_keys:
            specific_testcase = data_generated_through_LLM[testcase_index]
            duplicate_flag = check_for_duplicate(specific_testcase, created_data_so_far) 
            if duplicate_flag==False:
                count=count+1
                created_data_so_far[count] = specific_testcase
                created_data[count] = specific_testcase
                specific_testcase_lineage = dict()
                for key in created_data[count]:
                    try:
                        specific_testcase_lineage[key] = {created_data[count][key]:"generated"}
                    except:
                        try:
                            specific_testcase_lineage[key] = {str(created_data[count][key]):"generated"}
                        except:
                            specific_testcase_lineage[key] = {"dummy":"generated"}
                test_case_lineage["Testcase_"+str(count)] = specific_testcase_lineage
        return(created_data, test_case_lineage)

    # This method helps to generate testcases based on a test data file provided by the user
    def data_generation_from_testfile(self, optional_data_scenario):
        data_from_scenario = {}
        count = 0
        for scenario in optional_data_scenario:
            count = count + 1
            scenario_specific_data = dict()
            for param in list(scenario.keys()):
                try:
                    scenario_specific_data[param] = copy.deepcopy(scenario[param][0])
                except:
                    scenario_specific_data[param] = None
            if (len(scenario_specific_data) == 0):
                scenario_specific_data = {}
            data_from_scenario[count] = scenario_specific_data
        return (data_from_scenario)

    # This method is the wrapper on positive testcase generation
    def data_generation_main(self,transformed_tool_spec, original_tool_spec, optional_data_scenario):
        positive_testcase=None
        positive_test_case_lineage=None
        try:
            operation_type = list(transformed_tool_spec["operation"].keys())[0]
            if len(set(transformed_tool_spec["operation"][operation_type].keys()).intersection({"request_body_params","path_params","query_params"}))!=0:
                if (len(transformed_tool_spec["operation"][operation_type]["request_body_params"]) == 0 and len(transformed_tool_spec["operation"][operation_type]["path_params"]) == 0 and len(transformed_tool_spec["operation"][operation_type]["query_params"]) == 0):
                    created_data = dict()
                    test_case_lineage=dict()
                    created_data[1] = {}
                    test_case_lineage["Testcase_1"] = {}
                    logger.info("Test case generation complete. Successfully generated only one testcase",extra={'details':created_data})
                    return (created_data, test_case_lineage)
                else:
                    positive_testcase, positive_test_case_lineage = self.positive_testcase_generation(transformed_tool_spec, original_tool_spec, optional_data_scenario)
                    return (positive_testcase, positive_test_case_lineage)
            else:
                if len(list(transformed_tool_spec["operation"][operation_type].keys()))==0:
                    created_data = dict()
                    test_case_lineage=dict()
                    created_data[1] = {}
                    test_case_lineage["Testcase_1"] = {}
                    #logger.info("Test case generation complete. Successfully generated only one testcase",extra={'details':created_data})
                    logger.info("Test case generation complete. Successfully generated only one testcase")
                    return (created_data, test_case_lineage)
                else:
                    positive_testcase, positive_test_case_lineage = self.positive_testcase_generation(transformed_tool_spec, original_tool_spec, optional_data_scenario)
                    return (positive_testcase, positive_test_case_lineage)
        except:
            return (positive_testcase, positive_test_case_lineage)

    # This method comprises of the full pipeline for testcase generation        
    def testcase_generation_full_pipeline(self, tool_spec):
        no_test_data_generation = self.no_test_data_generation
        optional_data_scenario_path=self.optional_data_scenario_path
        llm_model_id=self.llm_model_id
        llm_platform=self.llm_platform
        transformed_tool_spec, original_tool_spec = tool_spec_post_process(tool_spec)
        if no_test_data_generation == False:
            if optional_data_scenario_path != None:
                with open(optional_data_scenario_path, 'r') as file:
                    optional_data_scenario = json.load(file)
            else:
                optional_data_scenario=None
            positive_testcases, test_case_lineage = self.data_generation_main(transformed_tool_spec, original_tool_spec, optional_data_scenario)
        else:
            if (optional_data_scenario_path == None):
                optional_data_scenario=None
                positive_testcases, test_case_lineage = self.data_generation_main(transformed_tool_spec, original_tool_spec, optional_data_scenario)
            else:
                with open(optional_data_scenario_path, 'r') as file:
                    optional_data_scenario = json.load(file)
                positive_testcases = self.data_generation_from_testfile(optional_data_scenario)
                #logger.info("Testcases obtained from the testfile",extra={'details':positive_testcases})
                logger.info("Testcases obtained from the testfile")
                test_case_lineage = None
        negative_testcases = self.negative_testcase_generation(positive_testcases, transformed_tool_spec)
        try:
            final_report = all_testcase_postprocess(positive_testcases, negative_testcases, transformed_tool_spec, original_tool_spec, llm_model_id, llm_platform)
            #logger.info("Basic report is created with testcases",extra={'details':final_report})
            logger.info("Basic report is created with testcases")
            return(final_report, test_case_lineage)
        except:
            #logger.info("Report could not created with testcases",extra={'details':tool_spec})
            logger.info("Report could not created with testcases")
            return(None, None)
    
    def generate_testcase_file(self, file):
        opId = file.split('_', -1)[0].split('/', -1)[-1]
        out_path = f"../data/{opId}_testcases.json"
        with open(file, 'r') as f:
            tool_spec = yaml.load(f, Loader=yaml.SafeLoader)
        final_report, _ = self.testcase_generation_full_pipeline(tool_spec)
        print(final_report)
        with open(out_path, 'w') as f:
            json.dump(final_report, f)

if __name__ == "__main__":
    import json
    print(os.getenv("OPENAI_BASE_URL"))
    llm_model_id = 'meta-llama/llama-3-3-70b-instruct'
    llm_platform = 'OpenAIProvider'
    wxo_tool_spec = json.load(open('wxo_tool_spec.json','r'))
    max_number_testcases_to_generate, no_test_data_generation, optional_data_scenario_path = 10, False, None
    tc_generator = TestcaseGeneration(llm_model_id, llm_platform, max_number_testcases_to_generate)
    ip_test_cases, _ = tc_generator.testcase_generation_full_pipeline(wxo_tool_spec)
    with open('ip_test_cases.json','w') as ipf:
       json.dump(ip_test_cases,ipf,indent=2)
    ipf.close()
