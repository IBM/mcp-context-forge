import json
import ast
from typing import Any
import aiofiles as aiof
import os
import re

from langchain_core.utils.json import parse_json_markdown
from mcpgateway.toolops.utils.llm_util import execute_prompt

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

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
    llm_config: dict[str, Any],
    logfolder: str,
    debug_mode: bool = False,
) -> str:
    modelid_toml = modelid.replace("/", "-")
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
    if modelid_toml in llm_config:
        params_dict["max_new_tokens"] = llm_config[modelid_toml]["max_new_tokens"]
        params_dict["stop_sequences"] = llm_config[modelid_toml]["stop_sequences"]
    else:
        params_dict["max_new_tokens"] = llm_config["default"]["max_new_tokens"]
        params_dict["stop_sequences"] = llm_config["default"]["stop_sequences"]

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

    #logger.debug("prompt_gen_str: " + prompt_gen_str)
    responses = execute_prompt(
        prompt_gen_str,
        model_id=params_dict["llm_model_name"],
        parameters=None,
        max_new_tokens=params_dict["max_new_tokens"],
        stop_sequences=params_dict["stop_sequences"],
    )
    #logger.debug("enrichment responses: " + str(responses))

    try:
        if debug_mode:
            async with aiof.open(promptfile, mode="a", encoding="utf-8") as f:
                await f.write(responses)

        responses = responses.replace("<|eom_id|>", "").strip()
        out_dict = parse_as_json_string(responses, params_dict["stop_sequences"])
        enriched_desc = get_first_value(out_dict, "new_description")

    except Exception as e1:
        logger.info("error3: " + str(e1) + ": promptfile : " + promptfile)
        logger.error(
            f"Exception {e1!s}! Invalid format returned by LLM1: {responses!s}",
            extra={"details": ""},
        )
        enriched_desc = ""

    if debug_mode:
        try:
            async with aiof.open(promptfile, mode="a", encoding="utf-8") as f:
                await f.write("\n\n" + "Refined LLM Output: " + enriched_desc)

        except Exception as e1:
            logger.error(
                f"Exception {e1!s} in gen_tool_param_desc_via_code!: ",
                extra={"details": ""},
            )
            enriched_desc = ""

    #logger.info("Return Value from generate_operation_description: %s", enriched_desc)
    logger.info("Tool description enrichment is successful")

    return enriched_desc
