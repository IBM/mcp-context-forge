import json
import sys
import os
import re
import time
from mcpgateway.toolops.utils.llm_util import execute_prompt

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

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
        if len(utterance) < 20 or is_invalid_utterance(utterance):
            continue
        elif '*' in utterance:
            if len(utterance.split('*',-1)[1]) > 10:
                utterance = utterance.split('*',-1)[1]
        utterance = utterance.lstrip('0123456789.-: ')
        utterance = utterance.strip().strip('"').strip("'")
        
        if clean_nl_utterances:
            utterance = utterance.replace('\\"','').replace("\\'",'')
            utterance = utterance.replace('"', '').replace("'", "")
        
        if utterance != '' and utterance not in out:
            try:
                if len(out) < int(max_nl_utterances_per_testcase):
                    out.append(utterance)
            except:
                out.append(utterance)
    return out
            
def rephrase_nl_query(nl_query, tool_spec, payload, llm_model_id, llm_platform, clean_nl_utterances, max_nl_utterances_per_testcase):
    prompt = preamble + str(tool_spec) + '\n\nInput Payload: ' + str(payload) +'\n\nutterance: '+ nl_query+'\n\nOutput: '
    stop_sequences=["\n\n\n", "<|endoftext|>"]
    result = execute_prompt(prompt, llm_model_id, llm_platform)
    result = result.split('\n')
    return format_output(result, clean_nl_utterances, max_nl_utterances_per_testcase)

def get_nl_query(tool_definition, input_parameter):
    nl_query = tool_definition['description'].split('\n')[0] + ' when '
    for key in input_parameter:
        if input_parameter[key][0] != 'NA':
            nl_query = nl_query  + key + ' is ' + str(input_parameter[key][0]) + ', '
    nl_query = nl_query.rstrip(', ')
    lis = nl_query.rsplit(',')
    if len(lis) > 1:
        nl_query = ','.join(lis[:-1]) + ', and ' + lis[-1]
    nl_query = nl_query.rstrip(' when ')
    return nl_query.strip()    