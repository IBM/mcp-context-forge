import json
import logging
from typing import Any

import aiofiles as aiof
from dotenv import load_dotenv
from langchain_openai import OpenAI
import os

from langchain_core.utils.json import parse_json_markdown
import re
from mcpgateway.services.mcp_client_chat_service import OpenAIConfig

logger = logging.getLogger(__name__)



'''
Using OpenAIProvider for LLM inferencing
'''
class OpenAIProvider:
    """
    OpenAI provider implementation (non-Azure).

    Manages connection and interaction with OpenAI API or OpenAI-compatible endpoints.

    Attributes:
        config: OpenAI configuration object.

    Examples:
        >>> config = OpenAIConfig(
        ...     api_key="sk-...",
        ...     model="gpt-4"
        ... )
        >>> provider = OpenAIProvider(config)
        >>> provider.get_model_name()
        'gpt-4'

    Note:
        The LLM instance is lazily initialized on first access for
        improved startup performance.
    """

    def __init__(self, config: OpenAIConfig):
        """
        Initialize OpenAI provider.

        Args:
            config: OpenAI configuration with API key and settings.

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
        """
        self.config = config
        self._llm = None
        logger.info(f"Initializing OpenAI provider with model: {config.model}")

    def get_llm(self) -> OpenAI:
        """
        Get OpenAI LLM instance with lazy initialization.

        Creates and caches the OpenAI chat model instance on first call.
        Subsequent calls return the cached instance.

        Returns:
            ChatOpenAI: Configured OpenAI chat model.

        Raises:
            Exception: If LLM initialization fails (e.g., invalid credentials).

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
            >>> # llm = provider.get_llm()  # Returns ChatOpenAI instance
        """
        if self._llm is None:
            try:
                kwargs: dict[str, Any] = {
                    "openai_api_key": self.config.api_key,
                    "model": self.config.model,
                    "temperature": self.config.temperature,
                    "max_tokens": self.config.max_tokens,
                    "timeout": self.config.timeout,
                    "max_retries": self.config.max_retries,                    
                }
                    
                if self.config.base_url:
                    kwargs["base_url"] = self.config.base_url
                kwargs["default_headers"] = {'RITS_API_KEY': self.config.api_key}
                self._llm = OpenAI(**kwargs)
                logger.info("OpenAI LLM instance created successfully")
            except Exception as e:
                logger.error(f"Failed to create OpenAI LLM: {e}")
                raise

        return self._llm

    def get_model_name(self) -> str:
        """
        Get the OpenAI model name.

        Returns:
            str: The model name configured for this provider.

        Examples:
            >>> config = OpenAIConfig(
            ...     api_key="sk-...",
            ...     model="gpt-4"
            ... )
            >>> provider = OpenAIProvider(config)
            >>> provider.get_model_name()
            'gpt-4'
        """
        return self.config.model



def execute_prompt(prompt, model_id = None, parameters=None, max_new_tokens=600, stop_sequences=["\n\n", "<|endoftext|>","###STOP###"]):
    try:
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "")
        model = os.getenv("OPENAI_MODEL", "")
        temperature= float(os.getenv("OPENAI_TEMPERATURE","0.7"))
        max_retries = int(os.getenv("OPENAI_MAX_RETRIES","2"))
        config = OpenAIConfig(api_key=api_key, base_url = base_url, temperature = temperature, 
                    model=model, max_tokens=max_new_tokens, max_retries = max_retries ,timeout=None)
        provider = OpenAIProvider(config)
        llm_instance = provider.get_llm()
        logger.info("Inferencing OpenAI provider LLM with the given prompt")
        llm_response = llm_instance.invoke(prompt, stop=stop_sequences)
        response = llm_response.replace("<|eom_id|>", "").strip()
        logger.info("Successful - Inferencing OpenAI provider LLM")
        return response
    except Exception as e:
        logger.error('Error in configuring LLM using OpenAI service provider - '+json.dumps({'Error': str(e)}))
        return ""




'''
enrichment methods : change the below methods to use execute_prompt method for inferencing LLM
'''


def split_str_by_given_list_of_str(input_str, str_lst):  # type: ignore # noqa: D103
    # add a '|' between the substrings to create the pattern for splitting
    pattern = "|".join(str_lst)
    # split the string using the pattern
    res = re.split(pattern, input_str)
    return res


def get_first_value(data, key):
    """Get the first value found for a specified key in JSON data."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        # Search nested dictionaries
        for value in data.values():
            if isinstance(value, dict | list):
                result = get_first_value(value, key)
                if result is not None:
                    return result
    elif isinstance(data, list):
        # Search each item in array
        for item in data:
            if isinstance(item, dict | list):
                result = get_first_value(item, key)
                if result is not None:
                    return result

    return ""


def parse_as_json_string(responses, stop_sequences): # type: ignore
    responses2 = split_str_by_given_list_of_str(responses, stop_sequences)[0]
    out_dict = {}
    if "```" in responses2:
        out_dict = parse_json_markdown(responses2)
    else:
        try:
            out_dict = json.loads(responses2)
        except Exception:
            try:
                responses2 = responses2.replace("'", '"')
                out_dict = json.loads(responses2)
            except Exception:
                out_dict = ast.literal_eval(responses2)
    return out_dict


    

async def generate_enriched_tool_description(
    tool_name: str,
    current_tool_description: str,
    input_schema: dict[str,Any],
    modelid: str,
    llm_platform: str,
    logfolder: str,
    debug_mode: bool = False,
) -> str:
    # modelid_toml = modelid.replace("/", "-")
    prompts_dir = "prompts/"
    currrent_dir = os.path.dirname(os.path.realpath(__file__))

    prompt_file_template = os.path.join(
        currrent_dir, prompts_dir, "tool_description.txt"
    )

    prompt_gen_str = ""
    async with aiof.open(prompt_file_template) as f:
        prompt_gen_str = await f.read()

    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Input: {"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + '"tool_name": "' + tool_name + '",'
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = (
        prompt_gen_str
        + '"current_tool_description": "'
        + current_tool_description
        + '",'
    )
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + '"input_schema": "' + json.dumps(input_schema)
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "}"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Output:"

    params_dict: dict[str, Any] = {}
    params_dict["llm_model_name"] = modelid
    # if modelid_toml in llm_config:
    #     params_dict["max_new_tokens"] = llm_config[modelid_toml]["max_new_tokens"]
    #     params_dict["stop_sequences"] = llm_config[modelid_toml]["stop_sequences"]
    # else:
    #     params_dict["max_new_tokens"] = llm_config["default"]["max_new_tokens"]
    #     params_dict["stop_sequences"] = llm_config["default"]["stop_sequences"]

    promptfile = (
        logfolder
        + "/"
        + tool_name.lower()
        + "_prompt_generate_operation_description.txt"
    )

    if debug_mode:
        async with aiof.open(promptfile, "w") as out:
            await out.write(prompt_gen_str)
            await out.flush()

    def configure_env_vars():
        env_file = os.path.join(currrent_dir, ".env")
        logger.info ("env_file: " + env_file)
        load_dotenv(env_file, override=True, verbose=True)

    configure_env_vars()
    api_key = os.getenv("RITS_API_KEY", "")
    rits_base_url = os.getenv("RITS_BASE_URL", "")
    rits_model_id = os.getenv("RITS_MODEL_ID", "")

    logger.info ("RITS_API_KEY: " + api_key)
    logger.info ("rits_base_url: " + rits_base_url)
    logger.info ("rits_model_id: " + rits_model_id)
    stop_seq = ["###STOP###", "\n\n", "\n\n\n", "<|endoftext|>"]
    config = OpenAIConfig(api_key=api_key, base_url = rits_base_url, temperature = 0.7, 
                model=rits_model_id, max_tokens=1000, timeout=None)
    provider = OpenAIProvider(config)
    provider.get_model_name()
    llm_instance = provider.get_llm()
    # response = llm_instance.invoke(prompt_gen_str)
    responses = llm_instance.invoke(prompt_gen_str, stop=stop_seq)
    logger.info ("response: " + responses)

    try:
        if debug_mode:
            async with aiof.open(promptfile, mode="a", encoding="utf-8") as f:
                await f.write(responses)

        responses = responses.replace("<|eom_id|>", "").strip()
        out_dict = parse_as_json_string(responses, stop_seq)
        logger.info ("out_dict: " + str(out_dict))
        enriched_desc = out_dict["new_description"]
        logger.info ("enriched_desc: " + str(enriched_desc))

    except Exception as e1:
        logger.info("error here3: " + str(e1) + ": promptfile : " + promptfile)
        logger.error(
            f"Exception {e1!s}! Invalid format returned by LLM1: {responses!s}",
            extra={"details": ""},
        )
        enriched_desc = ""

    if debug_mode:
        try:
            # with open(promptfile, "a", encoding="utf-8") as file:
            #     file.write("\n\n" + "Refined LLM Output: " + enriched_desc)
            async with aiof.open(promptfile, mode="a", encoding="utf-8") as f:
                await f.write("\n\n" + "Refined LLM Output: " + enriched_desc)

        except Exception as e1:
            logger.error(
                f"Exception {e1!s} in gen_tool_param_desc_via_code!: ",
                extra={"details": ""},
            )
            enriched_desc = ""

    logger.info("Return Value from generate_operation_description: %s", enriched_desc)

    return enriched_desc



if __name__=='__main__':
    load_dotenv(".env.example")
    print(os.getenv("OPENAI_BASE_URL"))
    execute_prompt("what is India GDP")








'''
from dotenv import load_dotenv
import os
import json
import logging
logger = logging.getLogger('toolops.utils.llm_util')
from openai import OpenAI
from ibm_watsonx_ai import Credentials as wx_credentials
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods
from ibm_watsonx_ai.foundation_models import ModelInference
from langchain_openai import ChatOpenAI
from langchain_ibm import ChatWatsonx
from toolops.exceptions import AgentLLMConfigurationError,LLMPlatformError
pwd = os.getcwd()




# IBM watsonx AI configurations
WATSONX_API_KEY = ''
WATSONX_URL = ''
WATSONX_PROJECT = ''
# RITS configurations
RITS_API_KEY = ''
RITS_BASE_URL= ''

def get_platform_credentials(llm_platform):
    global WATSONX_API_KEY, WATSONX_URL, WATSONX_PROJECT, RITS_API_KEY, RITS_BASE_URL
    if llm_platform == 'WATSONX':
        # IBM watsonx AI configurations
        WATSONX_API_KEY = os.environ.get('WATSONX_APIKEY')
        WATSONX_URL = os.environ.get('WML_API')
        WATSONX_PROJECT = os.environ.get('WATSONX_PROJECT_ID')
        
    elif llm_platform == 'RITS':
        RITS_API_KEY = os.environ.get('RITS_API_KEY')
        RITS_BASE_URL=os.environ.get('RITS_BASE_URL')
    

def check_llm_env_vars(llm_platform):
    if llm_platform not in ['RITS','WATSONX']:
        error_message = "Provided LLM_PLATFORM is - "+str(llm_platform)+" ,and supported LLM platforms are ['RITS','WATSONX'], please configure environment variables appropriately"
        raise LLMPlatformError(error_message)
    get_platform_credentials(llm_platform)
    if llm_platform == 'WATSONX':
        WATSONX_API_KEY = os.environ.get('WATSONX_APIKEY')
        WATSONX_URL = os.environ.get('WML_API')
        WATSONX_PROJECT = os.environ.get('WATSONX_PROJECT_ID')
        if WATSONX_API_KEY is None or WATSONX_URL is None or WATSONX_PROJECT is None:
            raise LLMPlatformError("Please configure all necessary environment varibles related to WATSONX LLM platform")
        else:
            logger.info('Using LLM platform details ', extra={'details': json.dumps({'LLM_PLATFORM':llm_platform,
                                                                                     'WML_URL':WATSONX_URL,
                                                                                     'WATSONX_PROJECT_ID':WATSONX_PROJECT})})
    if llm_platform == 'RITS':
        RITS_API_KEY = os.environ.get('RITS_API_KEY')
        RITS_BASE_URL=os.environ.get('RITS_BASE_URL')
        if RITS_API_KEY is None or RITS_BASE_URL is None :
            raise LLMPlatformError("Please configure all necessary environment varibles related to RITS LLM platform")
        else:
            logger.info('Using LLM platform details ', extra={'details': json.dumps({'LLM_PLATFORM':llm_platform,
                                                                                    'RITS_BASE_URL':RITS_BASE_URL,
                                                                                       })})
                                                                                      

def execute_prompt(prompt, model_id,llm_platform='WATSONX',parameters=None, max_new_tokens=600, stop_sequences=["\n\n", "<|endoftext|>"]):
    get_platform_credentials(llm_platform)
    if llm_platform == 'WATSONX':
        logger.info('using WATSONX LLM platform for SDK modules', extra={'details': json.dumps({'llm_model_id':model_id})})
        return execute_wxai_prompt(prompt, model_id, parameters, max_new_tokens, stop_sequences)
    elif llm_platform == 'RITS':
        logger.info('using RITS LLM platform for SDK modules', extra={'details': json.dumps({'llm_model_id':model_id})})
        return execute_rits_prompt(prompt, model_id, parameters, max_new_tokens, stop_sequences) 
    else:
        raise LLMPlatformError("Supported LLM platforms are ['RITS','WATSONX'], and configure apprpriately using environment variables")
    
def get_model_details(model_id):
    base_url_from_model_id = {
                            "mixtral-8x7b": {"id": "mistralai/mixtral-8x7B-instruct-v0.1", "url_id": "mixtral-8x7b-instruct-v01"}, 
                            "mixtral-8x22b": {"id": "mistralai/mixtral-8x22B-instruct-v0.1", "url_id": "mixtral-8x22b-instruct-v01"},
                            "granite-3.1-8b":{"id":"ibm-granite/granite-3.1-8b-instruct", "url_id":"granite-3-1-8b-instruct"},
                            "mistral-large":{"id":"mistralai/mistral-large-instruct-2407", "url_id":"mistral-large-instruct-2407"},
                            "llama-3-1-405b-instruct-fp8":{"id":"meta-llama/llama-3-1-405b-instruct-fp8", "url_id":"llama-3-1-405b-instruct-fp8"},
                            "granite-20b-functioncalling":{"id":"ibm-granite/granite-20b-functioncalling","url_id":"granite-20b-functioncalling"},
                            "llama-3-3-70b-instruct":{"id":"meta-llama/llama-3-3-70b-instruct","url_id":"llama-3-3-70b-instruct"}, 
                            "llama-4-maverick-17b-128e-instruct-fp8":{"id":"meta-llama/llama-4-maverick-17b-128e-instruct-fp8","url_id":"llama-4-mvk-17b-128e-fp8"}, 
                        }
    base_url=f"{RITS_BASE_URL}/{base_url_from_model_id[model_id]['url_id']}/v1"
    return base_url_from_model_id[model_id]["id"], base_url

def execute_rits_prompt(prompt, model_id, parameters=None, max_new_tokens=600, stop_sequences=["\n\n", "<|endoftext|>"]):
    try:
        # TODO: remove this line once everything is tested.
        #model_id=RITS_MODEL_ID
        model_name, base_url = get_model_details(model_id)
        client = OpenAI(
            base_url=base_url,
            api_key="NotRequiredSinceWeAreLocal",
            default_headers={
            "RITS_API_KEY": RITS_API_KEY,
        },)    
        logger.info('Configured LLM successfully using RITS Platform', extra={'details': json.dumps({'llm_model_id':model_id})})
        # print(prompt)
        completion = client.completions.create(
            model=model_name,
            max_tokens=max_new_tokens,
            temperature = 0,
            # top_k = 1,
            # top_p = 1,
            # min_tokens = 1,
            # temperature=temperature1,
            # best_of = 1,
            # response_format={"type": "json_object"},
            # stop = stop_sequences,
            prompt = prompt
        )
        result=completion.choices[0].text
        # tokens_used = completion.usage.total_tokens
        print(result.strip())
        return result.strip()
    except Exception as e:
        print(str(e))
        logger.error('Error in configuring LLM using RITS platform', extra={'details': json.dumps({'Error': str(e)})})
        return ""


    
def get_rits_chat_llm(agent_llm_model_id,agent_type):
    try:
        model_name, base_url = get_model_details(agent_llm_model_id.split("/")[-1])
        rits_chat_llm = ChatOpenAI(
            base_url=base_url,
            model=model_name,
            temperature=0,
            max_tokens=800,
            timeout=None,
            max_retries=2,
            api_key="NotRequiredSinceWeAreLocal",
            default_headers={
                "RITS_API_KEY": RITS_API_KEY,
            }
        )
        logger.info('Configured agent LLM successfully using RITS', extra={'details': json.dumps({'agent_type':agent_type,
                                                                                        'agent_llm_model_id':agent_llm_model_id})})
        return rits_chat_llm
    except Exception as e:
        raise AgentLLMConfigurationError(agent_llm_model_id,agent_type,str(e))
    
def get_agent_llm(agent_llm_model_id,agent_type,llm_platform):
    if llm_platform == 'RITS':
        logger.info('using RITS LLM platform for agent', extra={'details': json.dumps({'agnet_llm_model_id':agent_llm_model_id})})
        agent_llm = get_rits_chat_llm(agent_llm_model_id,agent_type)
    elif llm_platform == 'WATSONX':
        logger.info('using WATSONX LLM platform for agent', extra={'details': json.dumps({'agent_llm_model_id':agent_llm_model_id})})
        agent_llm = get_watsonx_chat_llm(agent_llm_model_id,agent_type)
    else:
        raise LLMPlatformError
    return agent_llm
'''
