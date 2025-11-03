import logging
import os
from ast import literal_eval
from pathlib import Path
from typing import Any

from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool import constants as cnst, prompt_utils
from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.docstring_utils import (
    compose_google_docstring,
    convert_google_to_sphinx,
    convert_sphinx_to_google,
    extract_elements,
    extract_from_python_code,
    extract_function_names_with_decorators,
    extract_method_and_docstring,
    generate_sphinx_docstring,
    is_google_format,
    merge_docstrings,
    parse_google_docstring,
    replace_docstring,
)
from toolops.enrichment.python_tool_enrichment.enrichment_utils.tool.utils import (
    CustomException,
    ToolDocstringElements,
    ToolElements,
    ToolEnrichmentConfig,
    ToolEnrichmentOptions,
    remove_duplicates,
)

logger = logging.getLogger(__name__)
script_dir = os.path.dirname(os.path.realpath(__file__))


def enrich(enrichment_config: ToolEnrichmentConfig):
    try:
        function_names_with_decorators = extract_function_names_with_decorators(
            enrichment_config.input_details.tool_source_code
        )
        method_name = ""
        for _, func_decorator in enumerate(function_names_with_decorators):
            if enrichment_config.input_details.tool_prefix in func_decorator[1]:
                method_name = func_decorator[0]
                break

        generated_description = ""
        generated_return_description = ""
        current_tool_description = ""
        generated_parameters_description = {}
        generated_input_examples = {}
        docstring_params = []
        docstring_params_desc = []
        current_return_description = ""
        result: dict[str, Any] = {}
        existing_values: dict[str, Any] = {}
        docstrings = '"""\n"""'
        orig_docstrings = ""

        if method_name:
            method_body_without_docstrings2 = ""
            docstrings = ""
            if enrichment_config.input_details.tool_source_code:
                method_body_without_docstrings2, docstrings, _ = (
                    extract_method_and_docstring(
                        enrichment_config.input_details.tool_source_code, method_name
                    )
                )

            if docstrings:
                logger.info("Extracted docstrings: %s", docstrings)
                # convert internally to sphinx format if not already
                # in sphinx format as the utils are based on sphinx
                # format
                if is_google_format(docstrings):
                    orig_docstrings = docstrings[:]
                    # do this to escape any newlines in parameter section of the docstring
                    # maybe we need to add similar functionality to sphinx style docstring also
                    parsed_obj = parse_google_docstring(orig_docstrings)
                    orig_docstrings = compose_google_docstring(parsed_obj)

                    docstrings = convert_google_to_sphinx(docstrings)

                (
                    current_tool_description,
                    docstring_params,
                    _,
                    docstring_params_desc,
                    current_return_description,
                    _,
                ) = extract_elements(docstrings)

            existing_parameter_descriptions = {}
            existing_parameter_examples = {}
            for idx, param in enumerate(docstring_params):
                if param:
                    if "Examples:" in docstring_params_desc[idx]:
                        parts = docstring_params_desc[idx].split("Examples:")
                        if len(parts) == 2:
                            examples1 = parts[1].strip()
                            examples_escaped = examples1.replace("\n", "\\n")
                            examples = literal_eval(examples_escaped)
                            if isinstance(examples, list):
                                existing_parameter_examples[param] = examples

                        existing_parameter_descriptions[param] = parts[0].strip()
                    else:
                        existing_parameter_descriptions[param] = docstring_params_desc[
                            idx
                        ]
                        existing_parameter_examples[param] = []

            (
                function_name,
                list_params1,
                list_params_dttypes1,
                method_source_code,
                method_signature,
                declarations,
                rest_of_code,
                _,
            ) = extract_from_python_code(
                method_name, enrichment_config.input_details.tool_source_code
            )

            logger.info("extract_python_method_elements2 returned: %s", function_name)
            logger.info(
                "extract_python_method_elements2 returned: %s", str(list_params1)
            )
            logger.info(
                "extract_python_method_elements2 returned: %s",
                str(list_params_dttypes1),
            )
            method_source_code = method_source_code.replace('"', r"\"")
            logger.info(
                "extract_python_method_elements2 returned: %s", method_source_code
            )
            logger.info(
                "extract_python_method_elements2 returned: %s", method_signature
            )

            existing_values[cnst.LABEL_ENRICHED_DESC] = current_tool_description
            existing_values[cnst.LABEL_ENRICHED_RETURN_DESCRIPTION] = (
                current_return_description
            )
            existing_values[cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS] = (
                existing_parameter_descriptions
            )
            existing_values[cnst.LABEL_ENRICHED_EXAMPLES] = existing_parameter_examples

            tool_docstring_elements = ToolDocstringElements(
                current_tool_description=current_tool_description,
                current_return_description=current_return_description,
                existing_parameter_descriptions=existing_parameter_descriptions,
                existing_parameter_examples=existing_parameter_examples,
            )

            toolElements = ToolElements(
                function_name=function_name,
                method_signature=method_signature,
                method_body_without_docstrings=method_body_without_docstrings2,
                declarations=declarations,
                rest_of_code=rest_of_code,
                tool_docstring_elements=tool_docstring_elements,
            )

            prompts_dir = "prompts/v2/"
            if cnst.USE_REST_OF_CODE_PROMPT:
                if enrichment_config.user_input.iterative_mode:
                    prompts_dir = (
                        prompts_dir
                        + "restofcode_based_prompts/user_feedback_based_prompts/"
                    )
                else:
                    prompts_dir = prompts_dir + "restofcode_based_prompts/"

            if enrichment_config.input_details.options.enable_tool_description_enrichment:
                prompt_file_template = os.path.join(
                    script_dir, prompts_dir, "toolops_description_via_code.txt"
                )
                generated_description = prompt_utils.generate_tool_description_via_code(
                    toolElements, prompt_file_template, enrichment_config
                )
                result[cnst.TOOL_DESCRIPTION_ENRICHMENT] = generated_description

            if enrichment_config.input_details.options.enable_tool_return_description_enrichment:
                prompt_file_template = os.path.join(
                    script_dir, prompts_dir, "toolops_return_description_via_code.txt"
                )
                generated_return_description = (
                    prompt_utils.gen_tool_return_desc_via_code(
                        toolElements, prompt_file_template, enrichment_config
                    )
                )
                result[cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT] = (
                    generated_return_description
                )
            # else:
            #     result[cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT] = (
            #         current_return_description
            #     )

            if (
                enrichment_config.input_details.options.enable_tool_parameter_description_enrichment
                and list_params1
            ):
                prompt_file_template = os.path.join(
                    script_dir,
                    prompts_dir,
                    "toolops_parameter_description_via_code.txt",
                )
                generated_parameters_description = (
                    prompt_utils.gen_tool_param_desc_via_code(
                        toolElements, prompt_file_template, enrichment_config
                    )
                )
                # if any parameter is missed by the llm, replace that with the existing value
                for key, value in existing_parameter_descriptions.items():
                    if (
                        key
                        not in generated_parameters_description[
                            cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS
                        ]
                    ):
                        generated_parameters_description[
                            cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS
                        ][key] = value

                result[cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT] = (
                    generated_parameters_description
                )
            # else:
            #     result[cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT] = (
            #         existing_parameter_descriptions
            #     )

            if (
                enrichment_config.input_details.options.enable_tool_example_enrichment
                and list_params1
            ):
                prompt_file_template = os.path.join(
                    script_dir,
                    prompts_dir,
                    "toolops_input_examples_generation_via_code.txt",
                )
                generated_input_examples = (
                    prompt_utils.gen_tool_input_examples_via_code(
                        toolElements, prompt_file_template, enrichment_config
                    )
                )
                # generated_input_examples[cnst.LABEL_ENRICHED_EXAMPLES]["limit"].append(35)
                if cnst.REMOVE_DUPLICATES_IN_GENERATED_EXAMPLES:
                    generated_input_examples = remove_duplicates(
                        generated_input_examples
                    )

                # if any parameter is missed by the llm, replace that with the existing value
                for key, value in existing_parameter_examples.items():
                    if (
                        key
                        not in generated_input_examples[cnst.LABEL_ENRICHED_EXAMPLES]
                    ):
                        generated_input_examples[cnst.LABEL_ENRICHED_EXAMPLES][key] = (
                            value
                        )

                result[cnst.TOOL_EXAMPLES_ENRICHMENT] = generated_input_examples
            # else:
            #     result[cnst.TOOL_EXAMPLES_ENRICHMENT] = existing_parameter_examples
    except Exception as e:
        logger.error(
            "Exception during processing tool source code: " + str(e),
            extra={"details": ""},
        )
        raise e
    else:
        result["enriched_method"] = method_name
        return result, existing_values, method_name, orig_docstrings, docstrings


def _write_to_file(
    enrichment_config: ToolEnrichmentConfig, orig_formatted_code, modified_code
):
    inp_path = Path(enrichment_config.input_details.tools_file)
    input_filename_without_extn = inp_path.stem

    model_id2 = (
        enrichment_config.tool_llm_config.model_id.split("/")[1]
        if "/" in enrichment_config.tool_llm_config.model_id
        else enrichment_config.tool_llm_config.model_id
    )

    original_filename_fullpath = ""
    if enrichment_config.output_config.debug_mode:
        original_filename = (
            model_id2
            + "_"
            + enrichment_config.input_details.prefix
            + "_"
            + input_filename_without_extn
            + "_before_enrichment.py"
        )
        original_filename_fullpath = (
            enrichment_config.output_config.prompts_log_folder + "/" + original_filename
        )
        with open(original_filename_fullpath, "w", encoding="utf-8") as f:
            f.write(orig_formatted_code)

    enriched_filename = input_filename_without_extn + "_" + model_id2 + "_en.py"
    enriched_filename_fullpath = (
        enrichment_config.output_config.logfolder + "/" + enriched_filename
    )
    with open(enriched_filename_fullpath, "w", encoding="utf-8") as f:
        f.write(modified_code)

    return enriched_filename, original_filename_fullpath


def _get_final_elements_of_modified_docstring(enrichments, existing_values):
    tool_description = ""
    tool_parameters_description = {}
    tool_return_description = ""
    tool_input_examples = {}

    if cnst.TOOL_DESCRIPTION_ENRICHMENT in enrichments:
        if cnst.LABEL_ENRICHED_DESC in enrichments[cnst.TOOL_DESCRIPTION_ENRICHMENT]:
            tool_description = enrichments[cnst.TOOL_DESCRIPTION_ENRICHMENT][
                cnst.LABEL_ENRICHED_DESC
            ]
    elif cnst.LABEL_ENRICHED_DESC in existing_values:
        tool_description = existing_values[cnst.LABEL_ENRICHED_DESC]

    if cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT in enrichments:
        if (
            cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS
            in enrichments[cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT]
        ):
            tool_parameters_description = enrichments[
                cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT
            ][cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS]
    elif cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS in existing_values:
        tool_parameters_description = existing_values[
            cnst.LABEL_ENRICHED_PARAM_DESCRIPTIONS
        ]

    if cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT in enrichments:
        if (
            cnst.LABEL_ENRICHED_RETURN_DESCRIPTION
            in enrichments[cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT]
        ):
            tool_return_description = enrichments[
                cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT
            ][cnst.LABEL_ENRICHED_RETURN_DESCRIPTION]
    elif cnst.LABEL_ENRICHED_RETURN_DESCRIPTION in existing_values:
        tool_return_description = existing_values[
            cnst.LABEL_ENRICHED_RETURN_DESCRIPTION
        ]

    if cnst.TOOL_EXAMPLES_ENRICHMENT in enrichments:
        if cnst.LABEL_ENRICHED_EXAMPLES in enrichments[cnst.TOOL_EXAMPLES_ENRICHMENT]:
            tool_input_examples = enrichments[cnst.TOOL_EXAMPLES_ENRICHMENT][
                cnst.LABEL_ENRICHED_EXAMPLES
            ]
    elif cnst.LABEL_ENRICHED_EXAMPLES in existing_values:
        tool_input_examples = existing_values[cnst.LABEL_ENRICHED_EXAMPLES]

    return (
        tool_description,
        tool_parameters_description,
        tool_input_examples,
        tool_return_description,
    )


def enrich_tool(enrichment_config: ToolEnrichmentConfig) -> tuple[str, str, dict, str]:
    if enrichment_config.user_input.iterative_mode:
        options = ToolEnrichmentOptions()
        if (
            enrichment_config.user_input.enrichment_type
            == cnst.TOOL_DESCRIPTION_ENRICHMENT
        ):
            options.enable_tool_description_enrichment = True
        elif (
            enrichment_config.user_input.enrichment_type
            == cnst.TOOL_PARAMETERS_DESCRIPTION_ENRICHMENT
        ):
            options.enable_tool_parameter_description_enrichment = True
        elif (
            enrichment_config.user_input.enrichment_type
            == cnst.TOOL_RETURN_DESCRIPTION_ENRICHMENT
        ):
            options.enable_tool_return_description_enrichment = True
        elif (
            enrichment_config.user_input.enrichment_type
            == cnst.TOOL_EXAMPLES_ENRICHMENT
        ):
            options.enable_tool_example_enrichment = True
        else:
            raise CustomException(
                f"Invalid enrichmentype: {enrichment_config.user_input.enrichment_type}"
            )

        enrichment_config.input_details.options = options

    enrichments: dict[str, Any] = {}
    existing_values: dict[str, Any] = {}
    method_name: str = ""
    current_docstring: str = ""

    enrichments, existing_values, method_name, original_docstring, current_docstring = (
        enrich(enrichment_config)
    )

    (
        tool_description,
        tool_parameters_description,
        tool_input_examples,
        tool_return_description,
    ) = _get_final_elements_of_modified_docstring(enrichments, existing_values)

    generated_docstring = generate_sphinx_docstring(
        tool_description,
        tool_parameters_description,
        tool_return_description,
        tool_input_examples,
    )

    final_docstring = generated_docstring
    if current_docstring:
        final_docstring = merge_docstrings(current_docstring, generated_docstring)

    if cnst.CONVERT_TO_GOOGLE_DOCSTRING_FORMAT:
        final_docstring = convert_sphinx_to_google(final_docstring)

    modified_code, orig_formatted_code = replace_docstring(
        enrichment_config.input_details.tool_source_code, method_name, final_docstring
    )

    enriched_filename, original_filename_fullpath = _write_to_file(
        enrichment_config, orig_formatted_code, modified_code
    )
    enrichments["updated_docstring"] = final_docstring
    enrichments["previous_docstring"] = original_docstring

    return (modified_code, enriched_filename, enrichments, original_filename_fullpath)
