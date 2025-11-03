import json
import sys
import os
import re
import numpy as np
from toolops.utils.llm_util import execute_prompt
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods
import time
import logging
logger = logging.getLogger('toolops.generation.nl_utterance_generation.nl_utterance_generation_util.nlg_util')

# preamble = 'Rephrase the following sentence into a user query with grammatically correct sentence. \n\ninput sentence:\n' 
# preamble = 'You are provided with an API spec and input payload for the API. You are also provided with a sample utterance. \
#     You are an expert user. Your task is to paraphrase the sample utterance into multiple sentences which users might ask. \
#     The paraphrased sentences should have the following two aspects:\n1. Fluency: Fluency describes how human-like the \
#     sentence is as per the examples below. The utterances should not simply provide the information one after another. \
#     Sentences that are natural and human-like would get a higher rating. \nGood Example: Can you book a flight from Delhi \
#     to NYC on the 15th of July. \nBad example: Can you book a flight where the from-location Delhi, destination is NYC \
#     and the date is 15th of July. \n\nAccuracy: Accuracy indicates if the entire input payload is accurately represented \
#     in the utterance. Missing values, additional values and incorrect values of parameters in the utterance should not \
#     be there in the utterance.\n\nAPI Spec: '

preamble = 'Given an API specification and an input payload, along with a sample utterance, your task as an expert user is to \
create multiple, distinct human-like sentences that convey the same information accurately. Each paraphrased sentence \
should:\n\n1. Maintain Fluency: Ensure the sentences are natural and conversational, avoiding robotic or overly formal \
language.\n   - Good Example: "Can you book a flight from Delhi to NYC on the 15th of July?"\n   - Bad Example: \
"Can you book a flight where the from-location is Delhi, the destination is NYC, and the date is 15th of \
July?"\n\n2. Ensure Accuracy: Make sure all details from the input payload are correctly represented without any \
omissions, additions, or errors.\n\n3. Preserve IDs: Do not modify, replace, or reformat any kind of IDs (such as user IDs, \
booking IDs, transaction IDs, etc.). Use them exactly as provided in the user utterance.\n\n4. No Introductory Text: Do not \
include lines like “Here are the paraphrases” or similar — output only the paraphrased sentences.\n\nPlease generate the paraphrased \
sentences based on the following\n\n API specification:'

def is_invalid_utterance(utterance):
    invalid_utterances = ['human-like sentences', 'paraphrased']
    for invalid_utterance in invalid_utterances:
        if invalid_utterance in utterance.lower():
            return True
    return False
            
def format_output(utterances, clean_nl_utterances, max_nl_utterances_per_testcase):
    out = []    
    for utterance in utterances:
        # print('#'*100)
        # print('Before: ',utterance)
        if len(utterance) < 20 or is_invalid_utterance(utterance):
            continue
        # if ':' in utterance:
        #     if len(utterance.split(':',1)[1]) > 10:
        #         utterance = utterance.split(':',1)[1]
        # elif '.' in utterance:
        #     if len(utterance.split('.',1)[1]) > 10:
        #         utterance = utterance.split('.',1)[1]
        elif '*' in utterance:
            if len(utterance.split('*',-1)[1]) > 10:
                utterance = utterance.split('*',-1)[1]
        utterance = utterance.lstrip('0123456789.-: ')
        utterance = utterance.strip().strip('"').strip("'")
        
        if clean_nl_utterances:
            utterance = utterance.replace('\\"','').replace("\\'",'')
            utterance = utterance.replace('"', '').replace("'", "")
            # utterance = re.escape(utterance)
        
        if utterance != '' and utterance not in out:
            try:
                if len(out) < int(max_nl_utterances_per_testcase):
                    out.append(utterance)
            except:
                out.append(utterance)
        # print('#'*100)
        # print('After: ',utterance)
    return out
            
def rephrase_nl_query(nl_query, tool_spec, payload, llm_model_id, llm_platform, clean_nl_utterances, max_nl_utterances_per_testcase):
    prompt = preamble + str(tool_spec) + '\n\nInput Payload: ' + str(payload) +'\n\nutterance: '+ nl_query+'\n\nOutput: '
    # print(prompt)
    stop_sequences=["\n\n\n", "<|endoftext|>"]
    parameters = {
        GenParams.RANDOM_SEED: np.random.randint(1, 50),
        GenParams.MIN_NEW_TOKENS: 0,
        GenParams.MAX_NEW_TOKENS: 10000,
        GenParams.DECODING_METHOD: DecodingMethods.SAMPLE,
        GenParams.REPETITION_PENALTY: 1,
        GenParams.STOP_SEQUENCES: stop_sequences,
        GenParams.TEMPERATURE: 0.7,
        GenParams.TOP_K: 50,
        GenParams.TOP_P: 1
    }
    result = execute_prompt(prompt, llm_model_id, llm_platform, parameters=parameters)
    # print(result)
    result = result.split('\n')
    return format_output(result, clean_nl_utterances, max_nl_utterances_per_testcase)

def get_nl_query(tool_definition, input_parameter):
    nl_query = tool_definition['description'].split('\n')[0] + ' when '
    # print(nl_query)
    for key in input_parameter:
        if input_parameter[key][0] != 'NA':
            nl_query = nl_query  + key + ' is ' + str(input_parameter[key][0]) + ', '
    nl_query = nl_query.rstrip(', ')
    lis = nl_query.rsplit(',')
    if len(lis) > 1:
        nl_query = ','.join(lis[:-1]) + ', and ' + lis[-1]
    nl_query = nl_query.rstrip(' when ')
    return nl_query.strip()    