import json
import sys
import os
import time

from mcpgateway.toolops.generation.nl_utterance_generation.nl_utterance_generation_utils import nlg_util
from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

class NlUtteranceGeneration:
    def __init__(self, llm_model_id, llm_platform, clean_nl_utterances=False, max_nl_utterances=3):
        self.llm_model_id = llm_model_id
        self.clean_nl_utterances = clean_nl_utterances
        self.max_nl_utterances = max_nl_utterances
        self.llm_platform = llm_platform
        
        
    def generate_nl(self, test_scenarios):
        logger.info('Started generating NL test cases for the tool')
        test_scenarios['llm_model_details']['nlg-model-id'] = self.llm_model_id
        test_scenarios['llm_platform_details']['nlg-platform'] = self.llm_platform
        tool_definition = test_scenarios['tool_definition']
        for parameter in test_scenarios['Test_scenarios']:
            nl_query = nlg_util.get_nl_query(tool_definition, parameter['input_parameters'], )
            refined_nl_query = nlg_util.rephrase_nl_query(nl_query, tool_definition, parameter['input_parameters'], self.llm_model_id, self.llm_platform,
                                                          self.clean_nl_utterances, self.max_nl_utterances)
            parameter['nl_utterance'] = refined_nl_query
        logger.info('NL utterance generation completed')
        
        return test_scenarios

    def generate_nl_file(self, file_path):
        opId = file_path.replace('.json', '').split('/', -1)[-1]
        out_path = f"./data/workshop_demo/sample_tool_enriched_nl_testcases.json"
        with open(file_path) as fil:
            test_scenarios = json.load(fil)
            test_scenarios = self.generate_nl(test_scenarios)
            with open(out_path, 'w') as out:
                json.dump(test_scenarios, out)

if __name__ == "__main__":
    file_path = './data/test_case_generation_output.json'
    file_path = './data/getApiV2Tickets_testcases.json'
    file_path = './data/workshop_demo/sample_tool_enriched_nl_testcases.json'
    LLM_PLATFORM = os.environ.get('LLM_PLATFORM')
    
    llm_model_id = 'mixtral-8x7b'
    if LLM_PLATFORM == 'WATSONX':
        llm_model_id = 'mistralai/mistral-medium-2505'
    clean_nl_utterances, max_nl_utterances_per_testcase = False, 3
    generator = NlUtteranceGeneration(llm_model_id, clean_nl_utterances, max_nl_utterances_per_testcase)
    generator.generate_nl_file(file_path)
    