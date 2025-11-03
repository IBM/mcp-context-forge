import ast
import asyncio
import base64
import datetime
import json
import logging
import os
from collections.abc import MutableMapping
from typing import Any

# from typing import Any, Literal, Optional
from pydantic import BaseModel, model_validator

# from pydantic.dataclasses import dataclass

logger = logging.getLogger(__name__)


class ToolEnrichmentOptions(BaseModel):
    """Request model for specification enrichment."""

    enable_tool_description_enrichment: bool = False
    enable_tool_parameter_description_enrichment: bool = False
    enable_tool_return_description_enrichment: bool = False
    enable_tool_example_enrichment: bool = False

    # Very important as it enables to convert a dictionary to this pydantic object
    @model_validator(mode="before")
    @classmethod
    def validate_to_json(cls, value):
        if isinstance(value, str):
            return cls(**json.loads(value))
        return value


class ToolDocstringElements(BaseModel):
    current_tool_description: str
    current_return_description: str
    existing_parameter_descriptions: dict
    existing_parameter_examples: dict | None = None


class ToolElements(BaseModel):
    function_name: str
    method_signature: str
    method_body_without_docstrings: str
    declarations: str
    rest_of_code: str
    tool_docstring_elements: ToolDocstringElements


class ToolInputDetails(BaseModel):
    tool_source_code: str
    options: ToolEnrichmentOptions
    tools_file: str = ""
    prefix: str = ""
    tool_prefix: str = "tool"


class ToolUserInput(BaseModel):
    iterative_mode: bool = False
    enrichment_type: str = ""
    user_feedback: dict[str, Any] | None = None


class ToolOutputConfig(BaseModel):
    logfolder: str
    prompts_log_folder: str
    debug_mode: bool = False


class ToolLLMConfig(BaseModel):
    model_id: str
    llm_platform: str
    llm_config: dict[str, Any]


class ToolEnrichmentConfig(BaseModel):
    input_details: ToolInputDetails
    user_input: ToolUserInput
    output_config: ToolOutputConfig
    tool_llm_config: ToolLLMConfig


class SpecEnrichmentOptions(BaseModel):
    """Request model for specification enrichment."""

    enable_op_description_enrichment: bool = True
    enable_parameter_description_enrichment: bool = False
    enable_example_enrichment: bool = False
    filter_for_op_description_enrichment: list = []
    filter_for_example_enrichment: list = []
    filter_for_parameter_description_enrichment: list = []
    # mode: str = "replace"

    # Very importantas it enables to convert a dictionary to this pydantic object
    @model_validator(mode="before")
    @classmethod
    def validate_to_json(cls, value):
        if isinstance(value, str):
            return cls(**json.loads(value))
        return value


class JsonFormatter(logging.Formatter):
    """Formatter to dump error message into JSON"""

    def format(self, record: logging.LogRecord) -> str:
        # details_value = ""
        # if hasattr(record, "details"):
        #     details_value = record.details

        record_dict = {
            "level": record.levelname,
            "date": self.formatTime(record),
            "message": record.getMessage(),
            # "module": record.module,
            # "details": details_value,
            "module": record.name,
            "lineno": record.lineno,
        }
        return json.dumps(record_dict)


class CustomException(Exception):
    """Custom Exception class for any skillops-enrichment related errors"""

    def __init__(self, message):
        self.error_message = f"Error type - CustomException , Message - {message} "

    def __str__(self):
        return self.error_message


def get_unique_sessionid() -> str:
    timestamp = ""
    timestamp = datetime.datetime.now().strftime(
        "%Y-%m-%dT%H-%M-%S.%fZ-"
    ) + base64.urlsafe_b64encode(os.urandom(6)).decode("ascii")

    return timestamp


def get_filepaths(directory):
    file_paths = []  # List which will store all of the full filepaths.

    # Walk the tree.
    for root, _, files in os.walk(directory):
        for filename in files:
            # Join the two strings in order to form the full filepath.
            filepath = os.path.join(root, filename)
            file_paths.append(filepath)  # Add it to the list.

    return file_paths  # Self-explanatory.


async def write_demo_output_to_file(llmoutput, outfile, skiplist=None):
    """
    Asynchronously writes demo output to a file.

    Args:
        llmoutput (dict): The output data to write.
        outfile (str): Path to the output file.
        skiplist (list): List of keys to skip when writing.

    Returns:
        dict: The processed output data that was written to the file.

    """
    loop = asyncio.get_running_loop()
    newobj = await loop.run_in_executor(
        None, write_demo_output_to_file2, llmoutput, outfile, skiplist
    )
    return newobj


def write_demo_output_to_file2(llmoutput, outfile, skiplist=None):
    """
    Writes demo output to a file after removing specified keys.

    Args:
        llmoutput (dict): The output data to write.
        outfile (str): Path to the output file.
        skiplist (list): List of keys to skip when writing.

    Returns:
        dict: The processed output data that was written to the file.

    """
    obj = llmoutput.copy()
    # newobj = delete_keys_from_dict(obj, skiplist)
    newobj = remove_nested_keys(obj, skiplist)
    with open(outfile, "w", encoding="utf-8") as write_file:
        json.dump(newobj, write_file, sort_keys=False, indent=4, separators=(",", ": "))
    return newobj


def remove_nested_keys(dictionary, keys_to_remove=None):
    """
    Recursively removes specified keys from a nested dictionary structure.

    Args:
        dictionary (dict): The dictionary to process.
        keys_to_remove (list): List of keys to remove from the dictionary.

    Returns:
        dict: The processed dictionary with specified keys removed.

    """
    if isinstance(dictionary, dict):
        if keys_to_remove is not None:
            for key in keys_to_remove:
                if key in dictionary:
                    del dictionary[key]

            if isinstance(dictionary, list):
                for elem in dictionary:
                    remove_nested_keys(elem, keys_to_remove)

            if isinstance(dictionary, dict):
                values_list = dictionary.values()
                for value in values_list:
                    if isinstance(value, dict):
                        remove_nested_keys(value, keys_to_remove)
                    if isinstance(value, list):
                        for elem in value:
                            remove_nested_keys(elem, keys_to_remove)

    return dictionary


# def is_numeric_type(field_type: str) -> bool:
#     """
#     Check if the field type is numeric.

#     Args:
#         field_type (str): The type of the field.

#     Returns:
#         bool: True if the field type is numeric, False otherwise.

#     """
#     numeric_types: list[str] = [
#         "integer",
#         "int",
#         "float",
#         "double",
#         "int32",
#         "int64",
#         "float32",
#         "number",
#     ]
#     if field_type in numeric_types:
#         return True
#     return False


# def is_string_type(field_type: str) -> bool:
#     """
#     Check if the field type is a string.

#     Args:
#         field_type (str): The type of the field.

#     Returns:
#         bool: True if the field type is a string, False otherwise.

#     """
#     string_types: list[str] = ["string", "text"]
#     if field_type in string_types:
#         return True
#     return False


def is_openapi_spec(json_data: dict):
    if not isinstance(json_data, dict):
        return False

    # Check for 'openapi' key for OpenAPI 3.x or 'swagger' for Swagger 2.0
    if "openapi" in json_data:
        # OpenAPI 3.x, check for basic structure
        if isinstance(json_data["openapi"], str):
            # Check for 'info' and 'paths' keys in OpenAPI 3.x
            if "info" in json_data and "paths" in json_data:
                return True
    elif "swagger" in json_data:
        # Swagger 2.0, check for basic structure
        if (
            isinstance(json_data["swagger"], str)
            and "info" in json_data
            and "paths" in json_data
        ):
            return True

    return False


def has_function_with_decorator(file_content: str, decorator_name: str) -> bool:
    # if not os.path.isfile(file_path):
    #     print(f"Error: File '{file_path}' does not exist.")
    #     return False

    # if not file_path.endswith(".py"):
    #     print(f"File '{file_path}' is not a Python file.")
    #     return False

    try:
        # with open(file_path, encoding="utf-8") as file:
        #     file_content = file.read()

        tree = ast.parse(file_content)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    # Check if it's a simple name decorator (e.g., @decorator_name)
                    if (
                        isinstance(decorator, ast.Name)
                        and decorator.id == decorator_name
                    ) or (
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr == decorator_name
                    ):
                        return True
                    # Check if it's a decorator with arguments (e.g., @decorator_name())
                    if isinstance(decorator, ast.Call):
                        if (
                            isinstance(decorator.func, ast.Name)
                            and decorator.func.id == decorator_name
                        ) or (
                            isinstance(decorator.func, ast.Attribute)
                            and decorator.func.attr == decorator_name
                        ):
                            return True

        return False

    # except SyntaxError:
    #     print(f"Error: File '{file_path}' is not a valid Python file.")
    #     return False
    except Exception as e:
        print(f"Error due ast parsing ': {e!s}")
        return False


def flatten_dict(d: MutableMapping, parent_key: str = "", sep: str = "."):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, MutableMapping):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def is_consecutive_subsequence(subsequence, main_sequence):
    """Check if subsequence appears as a consecutive subsequence within main_sequence."""
    if len(subsequence) == 0:
        return True
    if len(subsequence) > len(main_sequence):
        return False

    # Check all possible consecutive positions
    for i in range(len(main_sequence) - len(subsequence) + 1):
        # Check if the subsequence matches starting at position i
        if main_sequence[i : i + len(subsequence)] == subsequence:
            return True

    return False


def contains_any_from_nested_lists(string_list, nested_lists):
    """Alternative implementation using list comprehension and any()."""
    # If nested_lists is empty, return True (no patterns to match against)
    if not nested_lists:
        return True

    # Check if all sublists are empty (no meaningful patterns to match against)
    if all(len(sublist) == 0 for sublist in nested_lists):
        return True

    return any(
        is_consecutive_subsequence(sublist, string_list)
        for sublist in nested_lists
        if sublist
    )


# def remove_list_duplicates_in_dict(data_dict):
#     cleaned_dict = {}
#     for key, value in data_dict.items():
#         if isinstance(value, list):
#             cleaned_dict[key] = list(set(value))
#         else:
#             # If the value is not a list, keep it as is
#             cleaned_dict[key] = value
#     return cleaned_dict


# def remove_duplicates(data):
#     if isinstance(data, list):
#         unique_items = []
#         seen = set()
#         for item in data:
#             already_added = False
#             processed_item = remove_duplicates(item)  # Recurse for nested structures
#             if isinstance(
#                 processed_item, list
#             ):  # If it's a list, convert to tuple for hashing
#                 hashable_item = tuple(processed_item)
#             elif isinstance(processed_item, dict):
#                 processed_item = remove_duplicates(processed_item)
#                 unique_items.append(processed_item)
#                 already_added = True
#                 hashable_item = None
#             else:
#                 hashable_item = processed_item

#             if not already_added and hashable_item not in seen:
#                 seen.add(hashable_item)
#                 unique_items.append(processed_item)
#         return unique_items
#     elif isinstance(data, dict):
#         new_dict = {}
#         for key, value in data.items():
#             new_dict[key] = remove_duplicates(value)
#         return new_dict
#     else:
#         return data  # Return non-list/dict items as is


def make_hashable(obj):
    """
    Convert a nested structure (dict/list) into a hashable representation.
    
    Args:
        obj: Any object (dict, list, or primitive)
        
    Returns:
        A hashable representation of the object
    """
    if isinstance(obj, dict):
        return frozenset((k, make_hashable(v)) for k, v in obj.items())
    elif isinstance(obj, list):
        return tuple(make_hashable(item) for item in obj)
    elif isinstance(obj, set):
        return frozenset(make_hashable(item) for item in obj)
    else:
        # Primitive types are already hashable
        return obj


def remove_duplicates(data):
    """
    Remove duplicates from a dictionary or list.
    
    Args:
        data: Can be a dictionary or a list
        
    Returns:
        Processed dictionary or list with duplicates removed
    """
    # Handle list input
    if isinstance(data, list):
        new_list = []
        seen = set()
        for item in data:
            if isinstance(item, dict):
                processed_item = remove_duplicates(item)
                # Convert dict to hashable representation
                hashable_item = make_hashable(processed_item)
                if hashable_item not in seen:
                    seen.add(hashable_item)
                    new_list.append(processed_item)
            elif isinstance(item, list):
                # Recursively process nested lists
                processed_item = remove_duplicates(item)
                # Convert list to hashable representation
                hashable_item = make_hashable(processed_item)
                if hashable_item not in seen:
                    seen.add(hashable_item)
                    new_list.append(processed_item)
            else:
                if item not in seen:
                    seen.add(item)
                    new_list.append(item)
        return new_list
    
    # Handle dictionary input
    elif isinstance(data, dict):
        new_dict = {}
        for key, value in data.items():
            if isinstance(value, list):
                # For lists, remove duplicates recursively
                new_dict[key] = remove_duplicates(value)
            elif isinstance(value, dict):
                # Recursively process nested dictionaries
                new_dict[key] = remove_duplicates(value)
            else:
                # For other types, keep as is
                new_dict[key] = value
        return new_dict
    
    # For other types, return as is
    else:
        return data
