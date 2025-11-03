import ast
import json
import logging
import re
from typing import Any

from langchain_core.utils.json import parse_json_markdown

from toolops.utils.llm_util import execute_prompt
from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool import constants as cnst

from toolops.enrichment.python_tool_enrichment.enrichment_utils.common.utils import validate_llm_config
from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.utils import ToolElements, ToolEnrichmentConfig

logger = logging.getLogger(__name__)


def split_str_by_given_list_of_str(input_str, str_lst):
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


def parse_as_json_string(responses, stop_sequences):
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


def generate_tool_description_via_code(
    toolElements: ToolElements,
    prompt_file_template: str,
    enrichment_config: ToolEnrichmentConfig,
):
    modelid_toml = enrichment_config.tool_llm_config.model_id.replace("/", "-")
    validate_llm_config(enrichment_config.tool_llm_config.llm_config, modelid_toml)

    prompt_gen_str = ""
    with open(prompt_file_template, encoding="utf-8") as prompt_template:
        prompt_gen_str = prompt_template.read()

    tool_name = toolElements.function_name
    input_dct = {
        "tool_name": tool_name,
        "current_tool_description": toolElements.tool_docstring_elements.current_tool_description,
        "method_name": toolElements.function_name,
        "method_signature": toolElements.method_signature,
        "method_body": toolElements.method_body_without_docstrings,
    }
    if cnst.USE_REST_OF_CODE_PROMPT:
        input_dct["rest_of_the_code"] = toolElements.rest_of_code
        if enrichment_config.user_input.iterative_mode:
            if (
                enrichment_config.user_input.user_feedback
                and cnst.TOOL_DESCRIPTION_ENRICHMENT
                in enrichment_config.user_input.user_feedback
            ):
                input_dct["user_feedback"] = enrichment_config.user_input.user_feedback[
                    cnst.TOOL_DESCRIPTION_ENRICHMENT
                ]

    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Input: " + json.dumps(input_dct, indent=4)
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Output:"

    params_dict: dict[str, Any] = {}
    params_dict["llm_model_name"] = enrichment_config.tool_llm_config.model_id
    if modelid_toml in enrichment_config.tool_llm_config.llm_config:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["stop_sequences"]
    else:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["stop_sequences"]

    # if enrichment_config.input_details.prefix:
    #     prompt_file_name = (
    #         enrichment_config.input_details.prefix + "_prompt_tool_desc.txt"
    #     )
    # else:
    tool_name_mod = "".join(char for char in tool_name if char.isalnum())
    prompt_file_name = tool_name_mod + "_prompt_tool_desc.txt"

    if enrichment_config.output_config.debug_mode:
        promptfile = (
            enrichment_config.output_config.prompts_log_folder + "/" + prompt_file_name
        )
        with open(promptfile, "w", encoding="utf-8") as file:
            file.write(prompt_gen_str)

    responses = execute_prompt(
        prompt_gen_str,
        model_id=params_dict["llm_model_name"],
        llm_platform=enrichment_config.tool_llm_config.llm_platform,
        parameters=None,
        max_new_tokens=params_dict["max_new_tokens"],
        stop_sequences=params_dict["stop_sequences"],
    )
    # responses = execute_prompt2(
    #     prompt_gen_str,
    #     model_id=params_dict["llm_model_name"],
    #     max_new_tokens=params_dict["max_new_tokens"],
    #     stop_sequences=params_dict["stop_sequences"],
    # )

    try:
        if enrichment_config.output_config.debug_mode:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write(responses)

        # if not responses.startswith("["):
        #     responses2 = responses.split("}")[0] + "}"
        # else:
        #     responses2 = responses

        # # to make it a dictionary
        # responses2 = responses.split("}")[0] + "}"
        out_dict = parse_as_json_string(responses, params_dict["stop_sequences"])
        enriched_desc = get_first_value(out_dict, "new_description")
        # enriched_desc = out_dict["new_description"]

    except Exception as e1:
        logger.error(
            f"Exception {str(e1)}! Invalid format returned by LLM1: {str(responses)}",
            extra={"details": ""},
        )
        # enriched_desc = current_tool_description
        # enriched_desc = str(e1)
        enriched_desc = ""

    if enrichment_config.output_config.debug_mode:
        try:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write("\n\n" + "Refined LLM Output: " + enriched_desc)

        except Exception as e1:
            logger.error(
                f"Exception {str(e1)} in gen_tool_param_desc_via_code!: ",
                extra={"details": ""},
            )
            # enriched_desc = enriched_desc + "\n" + str(e1)
            enriched_desc = ""

    logger.info(
        "Return Value from gen_tool_param_desc_via_code: ",
        extra={"details": json.dumps({"enriched_desc": enriched_desc})},
    )
    enriched_desc_dict = {}
    enriched_desc_dict[cnst.LABEL_ENRICHED_DESC] = enriched_desc
    # enriched_desc_dict[cnst.LABEL_GENERATED_TOKEN_COUNT] = generated_token_count
    # enriched_desc_dict[cnst.LABEL_INPUT_TOKEN_COUNT] = input_token_count
    return enriched_desc_dict


def gen_tool_input_examples_via_code(
    toolElements: ToolElements,
    prompt_file_template: str,
    enrichment_config: ToolEnrichmentConfig,
):
    modelid_toml = enrichment_config.tool_llm_config.model_id.replace("/", "-")
    validate_llm_config(enrichment_config.tool_llm_config.llm_config, modelid_toml)

    prompt_gen_str = ""
    with open(prompt_file_template, encoding="utf-8") as prompt_template:
        prompt_gen_str = prompt_template.read()

    tool_name = toolElements.function_name
    input_dct: dict[str, Any] = {
        "tool_name": tool_name,
        "current_tool_description": toolElements.tool_docstring_elements.current_tool_description,
        "method_name": tool_name,
        "method_signature": toolElements.method_signature,
        "method_body": toolElements.method_body_without_docstrings,
    }
    if cnst.USE_REST_OF_CODE_PROMPT:
        input_dct["declarations"] = toolElements.declarations
        input_dct["rest_of_the_code"] = toolElements.rest_of_code

    input_dct["parameter_descriptions"] = json.dumps(
        toolElements.tool_docstring_elements.existing_parameter_descriptions
    )
    if cnst.USE_REST_OF_CODE_PROMPT and enrichment_config.user_input.iterative_mode:
        input_dct["parameter_examples"] = json.dumps(
            toolElements.tool_docstring_elements.existing_parameter_examples
        )
        if (
            enrichment_config.user_input.user_feedback
            and cnst.TOOL_EXAMPLES_ENRICHMENT
            in enrichment_config.user_input.user_feedback
        ):
            input_dct["user_feedback"] = json.dumps(
                enrichment_config.user_input.user_feedback[
                    cnst.TOOL_EXAMPLES_ENRICHMENT
                ]
            )

    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Input: " + json.dumps(input_dct, indent=4)
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Output:"

    params_dict: dict[str, Any] = {}
    params_dict["llm_model_name"] = enrichment_config.tool_llm_config.model_id
    if modelid_toml in enrichment_config.tool_llm_config.llm_config:
        if (
            "tool_example_generation"
            in enrichment_config.tool_llm_config.llm_config[modelid_toml]
        ):
            params_dict["max_new_tokens"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "tool_example_generation"
                ]["max_new_tokens"]
            )
            params_dict["stop_sequences"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "tool_example_generation"
                ]["stop_sequences"]
            )
        else:
            params_dict["max_new_tokens"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "max_new_tokens"
                ]
            )
            params_dict["stop_sequences"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "stop_sequences"
                ]
            )
    else:
        if (
            "tool_example_generation"
            in enrichment_config.tool_llm_config.llm_config["default"]
        ):
            params_dict["max_new_tokens"] = (
                enrichment_config.tool_llm_config.llm_config["default"][
                    "tool_example_generation"
                ]["max_new_tokens"]
            )
            params_dict["stop_sequences"] = (
                enrichment_config.tool_llm_config.llm_config["default"][
                    "tool_example_generation"
                ]["stop_sequences"]
            )
        else:
            params_dict["max_new_tokens"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "max_new_tokens"
                ]
            )
            params_dict["stop_sequences"] = (
                enrichment_config.tool_llm_config.llm_config[modelid_toml][
                    "stop_sequences"
                ]
            )

    # if enrichment_config.input_details.prefix:
    #     prompt_file_name = (
    #         enrichment_config.input_details.prefix + "_prompt_examples_gen.txt"
    #     )
    # else:
    tool_name_mod = "".join(char for char in tool_name if char.isalnum())
    prompt_file_name = tool_name_mod + "_prompt_examples_gen.txt"

    if enrichment_config.output_config.debug_mode:
        promptfile = (
            enrichment_config.output_config.prompts_log_folder + "/" + prompt_file_name
        )
        with open(promptfile, "w", encoding="utf-8") as file:
            file.write(prompt_gen_str)

    responses = execute_prompt(
        prompt_gen_str,
        model_id=params_dict["llm_model_name"],
        llm_platform=enrichment_config.tool_llm_config.llm_platform,
        parameters=None,
        max_new_tokens=params_dict["max_new_tokens"],
        stop_sequences=params_dict["stop_sequences"],
    )
    # responses = execute_prompt2(
    #     prompt_gen_str,
    #     model_id=params_dict["llm_model_name"],
    #     max_new_tokens=params_dict["max_new_tokens"],
    #     stop_sequences=params_dict["stop_sequences"],
    # )
    out_dict = {}
    try:
        if enrichment_config.output_config.debug_mode:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write(responses)

        # to make it a dictionary
        # responses2 = responses.split("}")[0] + "}"

        out_dict = parse_as_json_string(responses, params_dict["stop_sequences"])
    except Exception as e1:
        logger.error(
            f"Exception {str(e1)}! Invalid format returned by LLM5: {responses}",
            extra={"details": ""},
        )
        # responses2 = ""
        # out_dict["error1"] = str(e1)
        out_dict = {}

    if enrichment_config.output_config.debug_mode:
        try:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write("\n\n" + "Refined LLM Output: " + str(out_dict))

        except Exception as e1:
            logger.error(
                f"Exception {str(e1)} in gen_tool_input_examples_via_code!: ",
                extra={"details": ""},
            )
            # out_dict["error2"] = str(e1)
            out_dict = {}

    logger.info(
        "Return Value from gen_tool_input_examples_via_code: ",
        extra={"details": json.dumps({"out_dict": json.dumps(out_dict)})},
    )
    enriched_examples_dict = {}
    enriched_examples_dict[cnst.LABEL_ENRICHED_EXAMPLES] = out_dict
    # enriched_examples_dict[cnst.LABEL_GENERATED_TOKEN_COUNT] = generated_token_count
    # enriched_examples_dict[cnst.LABEL_INPUT_TOKEN_COUNT] = input_token_count

    return enriched_examples_dict


def gen_tool_param_desc_via_code(
    toolElements: ToolElements,
    prompt_file_template: str,
    enrichment_config: ToolEnrichmentConfig,
):
    modelid_toml = enrichment_config.tool_llm_config.model_id.replace("/", "-")
    validate_llm_config(enrichment_config.tool_llm_config.llm_config, modelid_toml)

    # prompt_template: toolops_parameter_description_via_code.txt
    prompt_gen_str = ""
    with open(prompt_file_template, encoding="utf-8") as prompt_template:
        prompt_gen_str = prompt_template.read()

    tool_name = toolElements.function_name
    input_dct = {
        "tool_name": tool_name,
        "current_tool_description": toolElements.tool_docstring_elements.current_tool_description,
        "method_name": tool_name,
        "method_signature": toolElements.method_signature,
        "method_body": toolElements.method_body_without_docstrings,
        "declarations": toolElements.declarations,
    }
    if cnst.USE_REST_OF_CODE_PROMPT:
        input_dct["rest_of_the_code"] = toolElements.rest_of_code
    input_dct["existing_parameter_descriptions"] = json.dumps(
        toolElements.tool_docstring_elements.existing_parameter_descriptions
    )
    if cnst.USE_REST_OF_CODE_PROMPT and enrichment_config.user_input.iterative_mode:
        if (
            enrichment_config.user_input.user_feedback
            and cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT
            in enrichment_config.user_input.user_feedback
        ):
            input_dct["user_feedback"] = json.dumps(
                enrichment_config.user_input.user_feedback[
                    cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT
                ]
            )

    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Input: " + json.dumps(input_dct, indent=4)
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Output:"

    params_dict: dict[str, Any] = {}
    params_dict["llm_model_name"] = enrichment_config.tool_llm_config.model_id
    if modelid_toml in enrichment_config.tool_llm_config.llm_config:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["stop_sequences"]
    else:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["stop_sequences"]

    # if enrichment_config.input_details.prefix:
    #     prompt_file_name = (
    #         enrichment_config.input_details.prefix + "_prompt_param_desc.txt"
    #     )
    # else:
    tool_name_mod = "".join(char for char in tool_name if char.isalnum())
    prompt_file_name = tool_name_mod + "_prompt_param_desc.txt"

    if enrichment_config.output_config.debug_mode:
        promptfile = (
            enrichment_config.output_config.prompts_log_folder + "/" + prompt_file_name
        )
        with open(promptfile, "w", encoding="utf-8") as file:
            file.write(prompt_gen_str)

    responses = execute_prompt(
        prompt_gen_str,
        model_id=params_dict["llm_model_name"],
        llm_platform=enrichment_config.tool_llm_config.llm_platform,
        parameters=None,
        max_new_tokens=params_dict["max_new_tokens"],
        stop_sequences=params_dict["stop_sequences"],
    )
    # responses = execute_prompt2(
    #     prompt_gen_str,
    #     model_id=params_dict["llm_model_name"],
    #     max_new_tokens=params_dict["max_new_tokens"],
    #     stop_sequences=params_dict["stop_sequences"],
    # )
    out_dict = {}

    try:
        if enrichment_config.output_config.debug_mode:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write(responses)

        # to make it a dictionary
        # responses2 = responses.split("}")[0] + "}"

        out_dict = parse_as_json_string(responses, params_dict["stop_sequences"])

    except Exception as e1:
        logger.error(
            f"Exception {str(e1)}! Invalid format returned by LLM4: {responses}",
            extra={"details": ""},
        )
        out_dict = {}

    if enrichment_config.output_config.debug_mode:
        try:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write("\n\n" + "Refined LLM Output: " + str(out_dict))

        except Exception as e1:
            logger.error(
                f"Exception {str(e1)} in gen_tool_param_desc_via_code!: ",
                extra={"details": ""},
            )
            # out_dict["error2"] = str(e1)
            out_dict = {}

    logger.info(
        "Return Value from gen_tool_param_desc_via_code: ",
        extra={"details": json.dumps({"out_dict": json.dumps(out_dict)})},
    )
    enriched_param_descriptions_dict = {}
    enriched_param_descriptions_dict[cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS] = out_dict
    # enriched_param_descriptions_dict[cnst.LABEL_GENERATED_TOKEN_COUNT] = generated_token_count
    # enriched_param_descriptions_dict[cnst.LABEL_INPUT_TOKEN_COUNT] = input_token_count
    return enriched_param_descriptions_dict


def gen_tool_return_desc_via_code(
    toolElements: ToolElements,
    prompt_file_template: str,
    enrichment_config: ToolEnrichmentConfig,
):
    modelid_toml = enrichment_config.tool_llm_config.model_id.replace("/", "-")
    validate_llm_config(enrichment_config.tool_llm_config.llm_config, modelid_toml)

    prompt_gen_str = ""
    with open(prompt_file_template, encoding="utf-8") as prompt_template:
        prompt_gen_str = prompt_template.read()

    tool_name = toolElements.function_name
    input_dct = {
        "tool_name": tool_name,
        "current_tool_description": toolElements.tool_docstring_elements.current_tool_description,
        "method_name": toolElements.function_name,
        "method_signature": toolElements.method_signature,
        "method_body": toolElements.method_body_without_docstrings,
        "declarations": toolElements.declarations,
    }
    if cnst.USE_REST_OF_CODE_PROMPT:
        input_dct["rest_of_the_code"] = toolElements.rest_of_code
    input_dct["current_return_description"] = (
        toolElements.tool_docstring_elements.current_return_description
    )

    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Input: " + json.dumps(input_dct, indent=4)
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "\n"
    prompt_gen_str = prompt_gen_str + "Output:"

    params_dict: dict[str, Any] = {}
    params_dict["llm_model_name"] = enrichment_config.tool_llm_config.model_id
    if modelid_toml in enrichment_config.tool_llm_config.llm_config:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            modelid_toml
        ]["stop_sequences"]
    else:
        params_dict["max_new_tokens"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["max_new_tokens"]
        params_dict["stop_sequences"] = enrichment_config.tool_llm_config.llm_config[
            "default"
        ]["stop_sequences"]

    # if enrichment_config.input_details.prefix:
    #     prompt_file_name = (
    #         enrichment_config.input_details.prefix + "_prompt_return_desc.txt"
    #     )
    # else:
    tool_name_mod = "".join(char for char in tool_name if char.isalnum())
    prompt_file_name = tool_name_mod + "_prompt_return_desc.txt"

    if enrichment_config.output_config.debug_mode:
        promptfile = (
            enrichment_config.output_config.prompts_log_folder + "/" + prompt_file_name
        )
        with open(promptfile, "w", encoding="utf-8") as file:
            file.write(prompt_gen_str)

    responses = execute_prompt(
        prompt_gen_str,
        model_id=params_dict["llm_model_name"],
        llm_platform=enrichment_config.tool_llm_config.llm_platform,
        parameters=None,
        max_new_tokens=params_dict["max_new_tokens"],
        stop_sequences=params_dict["stop_sequences"],
    )
    # responses = execute_prompt2(
    #     prompt_gen_str,
    #     model_id=params_dict["llm_model_name"],
    #     max_new_tokens=params_dict["max_new_tokens"],
    #     stop_sequences=params_dict["stop_sequences"],
    # )

    out_dict = {}
    try:
        if enrichment_config.output_config.debug_mode:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write(responses)

        # if not responses.startswith("["):
        #     responses2 = responses.split("}")[0] + "}"
        # else:
        #     responses2 = responses
        # to make it a dictionary
        # responses2 = responses.split("}")[0] + "}"
        out_dict = parse_as_json_string(responses, params_dict["stop_sequences"])
        retval = get_first_value(out_dict, "new_return_description")
        if not retval:
            if "error" in out_dict:
                retval = out_dict["error"]

        # if "new_return_description" in out_dict:
        #     retval = out_dict["new_return_description"]
        # elif "error" in out_dict:
        #     retval = out_dict["error"]

    except Exception:
        logger.exception(
            "Exception Invalid format returned by LLM6: %s", str(responses)
        )
        out_dict = {}
        retval = ""

    if enrichment_config.output_config.debug_mode:
        try:
            promptfile = (
                enrichment_config.output_config.prompts_log_folder
                + "/"
                + prompt_file_name
            )
            with open(promptfile, "a", encoding="utf-8") as file:
                file.write("\n\n" + "Refined LLM Output: " + retval)

        except Exception as e1:
            logger.error(
                f"Exception {str(e1)} in gen_tool_input_examples_via_code!: ",
                extra={"details": ""},
            )
            # retval = retval + "\n" + str(e1)
            retval = ""

    logger.info(
        "Return Value from gen_tool_return_desc_via_code: ",
        extra={"details": json.dumps({"retval": retval})},
    )

    enriched_return_description_dict = {}
    enriched_return_description_dict[cnst.LABEL_ENRICHED_RETURN_DESCRIPTION] = retval
    # enriched_return_description_dict[cnst.LABEL_GENERATED_TOKEN_COUNT] =generated_token_count
    # enriched_return_description_dict[cnst.LABEL_INPUT_TOKEN_COUNT] = input_token_count

    return enriched_return_description_dict
