import ast
import contextlib
import logging
import re  # Import regex module
import textwrap  # Import textwrap for dedenting/indenting
from typing import Any, Optional

import black
from docstring_parser import (  # Use the standard parser
    DocstringParam,
    DocstringReturns,
    DocstringStyle,
    compose,
    parse,
)

logger = logging.getLogger(__name__)


def _format_params_sphinx(params: list[DocstringParam]) -> str:
    """Formats parameters for Sphinx docstring."""
    lines = []
    for param in params:
        lines.append(f":param {param.arg_name}: {param.description or ''}")
        if param.type_name:
            lines.append(f":type {param.arg_name}: {param.type_name}")
    return "\n".join(lines)


def _format_returns_sphinx(returns: DocstringReturns | None) -> str:
    """Formats the return section for Sphinx docstring."""
    if not returns:
        return ""
    lines = []
    desc = returns.description or ""
    if returns.return_name:
        lines.append(f":return {returns.return_name}: {desc}")
    else:
        lines.append(f":return: {desc}")
    if returns.type_name:
        lines.append(f":rtype: {returns.type_name}")
    return "\n".join(lines)


def merge_docstrings(docstring1: str, docstring2: str) -> str:
    """
    Merges two Sphinx-style docstrings, prioritizing sections from the second.

    Replaces short/long descriptions and parameters from the first docstring
    with those from the second, if present. Updates the returns section if
    present in both. Preserves the 'Examples' section from the first docstring
    by extracting it manually.

    :param docstring1: The base docstring (Sphinx format).
    :type docstring1: str
    :param docstring2: The docstring whose sections will override/update the first (Sphinx format).
    :type docstring2: str
    :return: The merged docstring as a string (Sphinx format).
    :rtype: str
    """
    # --- Manual Extraction of Examples Section ---
    examples_section = ""
    # Use regex to find "Examples:", "Input Example:", or "Input Examples:",
    # possibly preceded by whitespace/newlines, and capture everything after it
    # Making sure it starts at the beginning of a line (using re.MULTILINE)
    # and ignoring case (re.IGNORECASE)
    match = re.search(
        r"^\s*(?:Examples|Input Example|Example \d+|Example|Input Examples):\s*$(.*?)(?:^\s*\w+:|\Z)",
        docstring1,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if match:
        # Preserve the original casing of the heading found
        heading = (
            match.group(0).strip().splitlines()[0]
        )  # Get the full matched heading line
        # Capture content
        content = match.group(1)
        # Dedent to remove common leading whitespace first
        dedented_content = textwrap.dedent(content)
        # Remove any leading blank lines *after* dedenting
        dedented_content = dedented_content.lstrip("\n")
        # Re-indent with a standard 4 spaces for consistent formatting
        indented_content = textwrap.indent(dedented_content, "    ")
        # Construct the final section, ensuring proper spacing
        # Strip trailing whitespace from indented_content to avoid extra blank lines at the end
        examples_section = f"\n\n{heading}\n{indented_content.rstrip()}"
        # Optional: Remove examples from docstring1 before parsing to avoid potential parser issues
        docstring1_parsed_part = docstring1[: match.start()].strip()
    else:
        docstring1_parsed_part = (
            docstring1  # Parse the whole thing if no examples found
        )

    # Parse the parts that docstring-parser *can* handle
    parsed1 = parse(docstring1_parsed_part, style=DocstringStyle.REST)
    parsed2 = parse(docstring2, style=DocstringStyle.REST)

    # Determine final descriptions
    short_desc = parsed2.short_description or parsed1.short_description
    long_desc = parsed2.long_description or parsed1.long_description
    if not long_desc and short_desc != parsed1.short_description:
        long_desc = short_desc
    if parsed1.short_description:
        short_desc_parsed1 = parsed1.short_description.replace('"""', "").strip()
        if not short_desc_parsed1:
            # no short desc given in source docstring. source docstring has just one line as the long desc.
            # Make the new long desc same as short desc so that we dont include original long desc (which
            # is already considered during the generation of the new description) in the merged docstring.
            # Example: get_job_change_reasons_by_category.py (workday) and
            # get_job_change_reasons_categories.py (workday)
            long_desc = short_desc

    # Determine final params
    params_list = parsed2.params if parsed2.params else parsed1.params
    params_str = _format_params_sphinx(params_list)

    # Determine final returns: Prioritize returns from docstring2 if available
    returns_obj = parsed2.returns if parsed2.returns else parsed1.returns
    returns_str = _format_returns_sphinx(returns_obj)

    # cleanup start
    if short_desc:
        short_desc = short_desc.replace('"""', "")
    if long_desc:
        long_desc = long_desc.replace('"""', "")
    if params_str:
        params_str = params_str.replace('"""', "")
    if returns_str:
        returns_str = returns_str.replace('"""', "")
    if examples_section:
        examples_section = examples_section.replace('"""', "")
    # cleanup end

    # --- Combine Parsed Parts ---
    if long_desc == short_desc:
        main_parts = [part for part in [short_desc, params_str, returns_str] if part]
    else:
        main_parts = [
            part for part in [short_desc, long_desc, params_str, returns_str] if part
        ]
    merged_body = "\n\n".join(main_parts).strip()

    # --- Append Manually Extracted Examples ---
    final_docstring = merged_body + examples_section
    final_docstring2 = '"""' + final_docstring.strip() + '"""'

    return final_docstring2


def extract_elements2(docstrings1):
    docstring = parse(docstrings1)
    current_tool_description = docstring.long_description
    return current_tool_description


def extract_method_and_docstring(
    tool_source_code: str, method_name: str
) -> tuple[str, str, str | None]:
    """
    Extract a method and its docstring from Python source code.

    Args:
        tool_source_code (Union[str, list]): Python source code as a string or list of lines
        method_name (str): Name of the method to extract

    Returns:
        Tuple[str, Optional[str], Optional[str]]: A tuple containing:
            - The method code without docstring (or None if not found)
            - The extracted docstring (or None if not found)
            - The modified source code with the docstring removed (or None if not found)

    """
    # if isinstance(tool_source_code, str):
    source_lines = tool_source_code.splitlines(keepends=True)
    # else:
    #     source_lines = tool_source_code

    source = "".join(source_lines)
    tree = ast.parse(source)

    # Find the method definition
    method_node = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == method_name
        ):
            method_node = node
            break

    if not method_node:
        return "", "", None

    # Get the line numbers where the method starts and ends
    start_line = method_node.lineno - 1  # Convert to 0-based index

    # Find the end of the function using AST node information
    end_line = 0  # just a hack
    if hasattr(method_node, "end_lineno"):
        # Python 3.8+ has end_lineno
        if method_node.end_lineno:
            end_line = method_node.end_lineno - 1  # Convert to 0-based
    else:
        # For older Python versions, find the last line of the function body
        last_node = method_node.body[-1] if method_node.body else method_node
        if last_node.end_lineno:
            end_line = (
                last_node.end_lineno - 1
                if hasattr(last_node, "end_lineno")
                else start_line
            )

    # Get the method source code with all comments
    method_lines = source_lines[start_line : end_line + 1]
    method_code = "".join(method_lines)

    # Extract the docstring using AST
    docstring = ast.get_docstring(method_node, clean=False)

    # Find the actual body start (excluding the docstring)
    # body_start = method_node.body[0].lineno - 1 if method_node.body else start_line

    if (
        docstring
        and method_node.body
        and isinstance(method_node.body[0], ast.Expr)
        # and isinstance(method_node.body[0].value, (ast.Str, ast.Constant))
        and isinstance(method_node.body[0].value, ast.Constant)
    ):
        # Get the docstring node
        docstring_node = method_node.body[0]
        doc_start = docstring_node.lineno - 1  # Convert to 0-based

        # Find the end of the docstring
        doc_end = 0  # just a hack
        if hasattr(docstring_node, "end_lineno"):
            if docstring_node.end_lineno:
                doc_end = docstring_node.end_lineno - 1  # Convert to 0-based
        else:
            # Fallback: find the end of the docstring by looking for closing quotes
            doc_end = doc_start
            docstring_quotes = None
            in_docstring = False

            for i in range(doc_start, min(end_line + 1, len(source_lines))):
                line = source_lines[i]
                stripped = line.strip()

                if not in_docstring and ('"""' in stripped or "'''" in stripped):
                    docstring_quotes = '"""' if '"""' in stripped else "'''"
                    in_docstring = True
                    if stripped.count(docstring_quotes) == 2:
                        doc_end = i
                        break
                elif in_docstring and docstring_quotes and docstring_quotes in stripped:
                    doc_end = i
                    break

        # Rebuild the method code without the docstring
        result_lines = []
        in_docstring_section = False

        # for i in range(len(method_lines)):
        for i, _ in enumerate(method_lines):
            line = method_lines[i]
            line_num = start_line + i

            if doc_start <= line_num <= doc_end:
                if not in_docstring_section:
                    # This is the first line of the docstring
                    # Keep the part before the docstring starts
                    if '"""' in line:
                        parts = line.split('"""', 1)
                        if len(parts) > 1:
                            result_lines.append(parts[0].rstrip() + "\n")
                    elif "'''" in line:
                        parts = line.split("'''", 1)
                        if len(parts) > 1:
                            result_lines.append(parts[0].rstrip() + "\n")
                    in_docstring_section = True
                # Skip the docstring content
                continue

            result_lines.append(line)

        method_code = "".join(result_lines)

        # Rebuild the modified source code with the docstring removed
        modified_source_lines = []
        # for i in range(len(source_lines)):
        for i, _ in enumerate(source_lines):
            if doc_start <= i <= doc_end:
                if not in_docstring_section:
                    # This is the first line of the docstring
                    # Keep the part before the docstring starts
                    if '"""' in source_lines[i]:
                        parts = source_lines[i].split('"""', 1)
                        if len(parts) > 1:
                            modified_source_lines.append(parts[0].rstrip() + "\n")
                    elif "'''" in source_lines[i]:
                        parts = source_lines[i].split("'''", 1)
                        if len(parts) > 1:
                            modified_source_lines.append(parts[0].rstrip() + "\n")
                    in_docstring_section = True
                # Skip the docstring content
                continue
            modified_source_lines.append(source_lines[i])

        modified_source = "".join(modified_source_lines)

        return method_code, docstring, modified_source

    if docstring:
        return method_code, docstring, tool_source_code
    return method_code, "", tool_source_code


def add_docstring(source_code, new_docstring, function_name=None):
    # Parse the source code into an AST
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        msg = "Invalid Python syntax"
        raise ValueError(msg) from e

    # Find the target function
    target_function = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and (
            function_name is None or node.name == function_name
        ):
            target_function = node
            break

    if target_function is None:
        function_spec = f"'{function_name}'" if function_name else "any function"
        msg = f"Could not find {function_spec} in the source code"
        raise ValueError(msg)

    # Get the line numbers for the function definition
    func_lineno = target_function.lineno

    # Check if the function already has a docstring
    if (
        target_function.body
        and isinstance(target_function.body[0], ast.Expr)
        and isinstance(target_function.body[0].value, ast.Constant)
        and isinstance(target_function.body[0].value.value, str)
    ):
        msg = f"Function '{target_function.name}' already has a docstring"
        raise ValueError(msg)

    # Split the source code into lines
    lines = source_code.splitlines(True)  # Keep line endings

    # Find the position to insert the docstring (after the function definition line)
    # We need to find where the function body starts
    indent = None
    body_start_line = func_lineno

    # For multi-line function signatures, we need to find the line with the colon
    # and ensure we're tracking parentheses to handle complex signatures
    in_function_def = True
    paren_count = 0
    found_opening_paren = False

    for i in range(func_lineno - 1, len(lines)):
        line = lines[i]

        if in_function_def:
            # Count opening and closing parentheses
            for char in line:
                if char == "(":
                    found_opening_paren = True
                    paren_count += 1
                elif char == ")":
                    paren_count -= 1

            # Check if this line contains the end of function definition (colon after balanced parentheses)
            if found_opening_paren and paren_count == 0 and ":" in line.split(")")[-1]:
                in_function_def = False
                body_start_line = i + 1

                # Get indentation from the first line of the function body
                for j in range(body_start_line, len(lines)):
                    if lines[j].strip():  # Non-empty line
                        indent_match = re.match(r"^(\s+)", lines[j])
                        indent = (
                            indent_match.group(1) if indent_match else ""
                        )  # No indentation (unusual but possible)
                        break
                break

    # If we couldn't determine indentation, use 4 spaces as default
    if indent is None:
        indent = "    "

    # Format the docstring with proper indentation
    docstring_lines = new_docstring.splitlines()
    # formatted_docstring = [f"{indent}\"\"\"\n"]
    formatted_docstring = []
    for line in docstring_lines:
        if line.strip():
            formatted_docstring.append(f"{indent}{line}\n")
        else:
            formatted_docstring.append("\n")
    # formatted_docstring.append(f"{indent}\"\"\"\n")

    # Insert the docstring after the function definition
    result = lines[:body_start_line] + formatted_docstring + lines[body_start_line:]

    return "".join(result)


def extract_elements(docstring_text):
    current_tool_description = ""
    docstring_params = []
    docstring_params_types = []
    docstring_params_desc = []
    return_description = ""
    long_description = ""  # Also extract long description if needed
    examples_content = ""  # To store extracted example content
    docstring_for_parsing = docstring_text  # Start with the full docstring

    if docstring_text:
        # --- Manual Extraction of Examples Section (before parsing) ---
        try:
            # Regex to find various example headings
            match = re.search(
                r"^\s*(?:Examples|Input Example|Example \d+|Example|Input Examples):\s*$(.*?)(?:^\s*\w+:|\Z)",
                docstring_text,
                re.MULTILINE | re.DOTALL | re.IGNORECASE,
            )
            if match:
                # Capture content
                content = match.group(1)
                # Dedent to remove common leading whitespace
                dedented_content = textwrap.dedent(content)
                # Remove any leading/trailing blank lines/whitespace after dedenting
                examples_content = dedented_content.strip()

                # Prepare the docstring for the parser by removing the example section
                docstring_for_parsing = docstring_text[: match.start()].rstrip()
        except Exception as e:
            print(f"Error during example extraction: {e}")
            # Proceed with parsing the original docstring if example extraction fails
            docstring_for_parsing = docstring_text

        # --- Parse the main docstring structure (without examples) ---
        try:
            # Parse using docstring-parser for reST/Sphinx style
            parsed = parse(docstring_for_parsing, style=DocstringStyle.REST)

            short_description = parsed.short_description
            current_tool_description = short_description or ""
            long_description = parsed.long_description or ""

            # Combine descriptions if long exists, otherwise use short
            if long_description:
                current_tool_description = (
                    f"{short_description}\n\n{long_description}".strip()
                )
            else:
                current_tool_description = parsed.short_description or ""
            current_tool_description = current_tool_description.strip()

            for param in parsed.params:
                docstring_params.append(param.arg_name)
                docstring_params_types.append(param.type_name or "")
                docstring_params_desc.append(param.description or "")

            if parsed.returns:
                return_description = parsed.returns.description or ""
                # Optionally include type name if needed:
                # if parsed.returns.type_name:
                #    return_description += f" (Type: {parsed.returns.type_name})"
        except Exception as e:
            print(f"Error parsing docstring: {e}")
            # Optionally return defaults or raise the exception

    # cleanup start
    if current_tool_description:
        current_tool_description = current_tool_description.replace('"""', "").strip()
    if return_description:
        return_description = return_description.replace('"""', "").strip()
    # cleanup end

    return (
        current_tool_description,
        docstring_params,
        docstring_params_types,
        docstring_params_desc,
        return_description,
        examples_content,  # Add examples to the return tuple
    )


def extract_from_python_code(
    method_name: str, source_code: str, use_imports: bool = True
) -> tuple[str, list[Any], list[Any], str, str, str, str, str]:
    # Parse the source code into an AST
    tree = ast.parse(source_code)

    # Initialize variables to store the results
    method_body = ""
    method_start = 0
    method_end = 0
    import_lines: set[int] = set()  # Track import statement line numbers
    declaration_lines = set()  # Track declaration line numbers

    # Initialize variables to store the results
    parameters = []
    param_types = []
    method_body = ""
    signature = ""
    docstrings = ""

    class FunctionVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            nonlocal method_body, method_start, method_end
            nonlocal parameters, param_types, method_body, signature, docstrings

            if node.name == method_name:
                # Calculate start line (including decorators)
                method_start = int(node.lineno - len(node.decorator_list) - 1)
                method_end = node.end_lineno

                # Get the source lines
                # source_lines = source_code.splitlines()

                # Extract method body including decorators
                # method_body = "\n".join(source_lines[method_start:method_end])

                # Extract parameter names and types
                parameters = [arg.arg for arg in node.args.args]
                param_types = [
                    (
                        ast.get_source_segment(source_code, arg.annotation)
                        if arg.annotation
                        else "None"
                    )
                    for arg in node.args.args
                ]

                # Extract the method body as a string
                method_body = ast.get_source_segment(source_code, node)

                # Create the method signature
                param_list = ", ".join(
                    [
                        f"{name}: {ptype}"
                        for name, ptype in zip(parameters, param_types, strict=False)
                    ]
                )
                return_type = (
                    ast.get_source_segment(source_code, node.returns)
                    if node.returns
                    else "None"
                )
                signature = f"{node.name}({param_list}) -> {return_type}"
                docstrings = ast.get_docstring(node)
                return

        def visit_ClassDef(self, node):
            # Track class declarations including decorators
            start_line = int(node.lineno - len(node.decorator_list) - 1)
            end_line = 0  # just a hack
            if node.end_lineno:
                end_line = int(node.end_lineno)
            declaration_lines.update(
                range(start_line, end_line)
            )  # Track all lines in class
            self.generic_visit(node)

        def visit_Assign(self, node):
            # Track variable declarations including multi-line assignments
            start_line = int(node.lineno - 1)  # Ensure this is an integer
            for _ in node.targets:
                declaration_lines.add(start_line)

            # Check for various types of assignments
            if isinstance(node.value, ast.Tuple | ast.List | ast.Dict | ast.Set):
                # If it's a tuple, list, dictionary, or set assignment, track all lines
                end_line = node.value.end_lineno
                if end_line:
                    declaration_lines.update(range(start_line, end_line))
            else:
                declaration_lines.add(
                    node.lineno - 1
                )  # Track single line variable declarations

        def visit_Import(self, node):
            import_lines.add(node.lineno - 1)  # Line numbers are 1-based

        def visit_ImportFrom(self, node):
            import_lines.add(node.lineno - 1)  # Line numbers are 1-based

    # Create an instance of the visitor and visit the AST
    visitor = FunctionVisitor()
    visitor.visit(tree)

    # Split the source code into lines
    source_lines = source_code.splitlines()

    # Get the declarations
    declarations = [
        line for i, line in enumerate(source_lines) if i in declaration_lines
    ]

    # Get the rest of the code, optionally excluding imports
    rest_lines = [
        line
        for i, line in enumerate(source_lines)
        if (i < method_start or i >= method_end)
        and (use_imports or i not in import_lines)
        and i not in declaration_lines
    ]

    rest_of_code = "\n".join(rest_lines)

    return (
        method_name,
        parameters,
        param_types,
        method_body,
        signature,
        "\n".join(declarations),
        rest_of_code,
        docstrings,
    )


def extract_function_names_with_decorators(
    tool_source_code1: str,
) -> list[tuple[str, list[str]]]:
    try:
        # Parse the source code into an AST
        tree = ast.parse(tool_source_code1)

        # Dictionary to store function names and their decorators
        func_names_with_decorators: list[tuple[str, list[str]]] = []

        # Traverse the AST
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Get function name
                function_name = node.name

                # Get decorators
                decorators = []
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Name):
                        decorators.append(decorator.id)
                    elif isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Name):
                            decorators.append(decorator.func.id)
                        elif isinstance(decorator.func, ast.Attribute):
                            # Handle decorators like @abc.decorator4()
                            decoratorname = (
                                f"{decorator.func.value.id}.{decorator.func.attr}"  # type: ignore
                            )
                            decorators.append(decoratorname)
                    elif isinstance(decorator, ast.Attribute):
                        # Handle decorators like @abc.decorator4 (without parentheses)
                        decoratorname = f"{decorator.value.id}.{decorator.attr}"  # type: ignore
                        decorators.append(decoratorname)

                # Store in dictionary
                # functions[function_name] = decorators
                func_names_with_decorators.append((function_name, decorators))

    except SyntaxError as e:
        msg = f"Invalid Python code: {e!s}"
        raise ValueError(msg) from e

    return func_names_with_decorators


def generate_sphinx_docstring(
    description: str,
    params: dict[str, Any],
    return_desc: str,
    tool_input_examples: dict[str, Any],
) -> str:
    """
    Generates a Sphinx-style docstring.

    :param description: A brief description of the function.
    :param params: A dictionary of parameter names and their descriptions.
    :param return_desc: A description of the return value.
    :param tool_input_examples: A dictionary of parameter names and their examples.
    :return: A formatted docstring in Sphinx format.
    """
    docstring2 = '"""'
    if description:
        docstring2 += f"{description}\n\n"

    for param, param_desc in params.items():
        if param_desc:
            docstring2 += f":param {param}: {param_desc}"
            # docstring2 += "\n"
            if param in tool_input_examples:
                if tool_input_examples[param]:
                    if docstring2 and not docstring2.strip().endswith("."):
                        docstring2 = docstring2.strip() + ". "
                    if docstring2.endswith(" "):
                        docstring2 += "Examples: "
                    else:
                        docstring2 += " Examples: "
                    docstring2 += str(tool_input_examples[param]) + "\n"
                else:
                    docstring2 += "\n"
            else:
                docstring2 += "\n"

    if return_desc:
        docstring2 += "\n"
        docstring2 += f":return: {return_desc}\n"

    docstring2 += '"""'
    return docstring2


@contextlib.contextmanager
def quiet_blib2to3():
    loggers = [
        logging.getLogger(n)
        for n in logging.root.manager.loggerDict  # pylint: disable=no-member.
        if n.startswith("blib2to3")
    ]
    prev = [(lgger.level, lgger.propagate) for lgger in loggers]
    try:
        for lgger in loggers:
            lgger.setLevel(logging.ERROR)
            lgger.propagate = False
        yield
    finally:
        for lgger, (lvl, prop) in zip(loggers, prev):
            lgger.setLevel(lvl)
            lgger.propagate = prop


def replace_docstring(source_code, method_name, new_docstring2, logger2=None):
    try:
        _, _, mod_source_code = extract_method_and_docstring(source_code, method_name)

        orig_formatted_code = source_code
        formatted_code3 = source_code
        if mod_source_code:
            modified_code = add_docstring(mod_source_code, new_docstring2, method_name)

            with quiet_blib2to3():
                formatted_code3 = black.format_str(
                    modified_code,
                    mode=black.FileMode(line_length=88, string_normalization=False),
                )
                orig_formatted_code = black.format_str(
                    source_code,
                    mode=black.FileMode(line_length=88, string_normalization=False),
                )

    except Exception as e:
        if logger2:
            logger2.exception("Exception in replace_docstring")
        else:
            print(f"Exception got : {e!s}")
        return source_code, source_code
    else:
        return formatted_code3, orig_formatted_code


def detect_docstring_style(docstring: str) -> str | None:
    if not docstring or not docstring.strip():
        return None

    styles = {
        "google": DocstringStyle.GOOGLE,
        "sphinx": DocstringStyle.REST,  # Sphinx uses reST style
    }

    best_style = None
    max_score = 0
    docstring_lower = docstring.lower()

    # First, check for clear indicators in the docstring
    has_google_indicators = any(
        marker in docstring_lower
        for marker in ["args:", "returns:", "yields:", "raises:", "examples:"]
    )
    has_sphinx_indicators = any(
        marker in docstring_lower
        for marker in [":param", ":return", ":rtype", ":type", ":raise"]
    )

    # If we have clear indicators, return the corresponding style
    if has_google_indicators and not has_sphinx_indicators:
        return "google"
    elif has_sphinx_indicators and not has_google_indicators:
        return "sphinx"

    # If no clear indicators or conflicting indicators, use the parser
    for style_name, style in styles.items():
        try:
            parsed = parse(docstring, style=style)
            # Calculate a weighted score based on parsed elements
            score = sum(
                [
                    2 if parsed.short_description else 0,  # More weight to description
                    1 if parsed.long_description else 0,
                    len(parsed.params) * 2,  # More weight to params
                    2 if parsed.returns else 0,  # More weight to returns
                    len(parsed.raises) if hasattr(parsed, "raises") else 0,
                ]
            )

            # Additional weight if style matches the docstring patterns
            if style_name == "google" and (
                "args:" in docstring_lower or "returns:" in docstring_lower
            ):
                score += 2
            elif style_name == "sphinx" and (
                ":param" in docstring_lower or ":return" in docstring_lower
            ):
                score += 2

            if score > max_score or (score == max_score and style_name == best_style):
                max_score = score
                best_style = style_name

        except Exception:
            continue

    # If we couldn't confidently detect a style, make a guess based on common patterns
    if max_score == 0:
        if ":param" in docstring_lower and ":return" in docstring_lower:
            return "sphinx"
        if "args:" in docstring_lower and "returns:" in docstring_lower:
            return "google"

    return best_style


def convert_sphinx_to_google(docstring: str) -> str:
    if not is_sphinx_format(docstring):
        return docstring

    if not docstring:
        return ""

    # Parse a docstring
    parsed_doc = parse(docstring, style=DocstringStyle.REST)
    # Convert to Google style
    parsed_doc.style = DocstringStyle.GOOGLE
    result = compose(parsed_doc, style=DocstringStyle.GOOGLE)

    # Post-process to fix any remaining colon issues - this is fix for
    # docstring_parser bug which prepends a : before the return
    # description
    lines = result.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("Returns:"):
            next_line = i + 1
            if next_line < len(lines) and lines[next_line].strip().startswith(":"):
                # Find the first non-whitespace character
                stripped = lines[next_line].lstrip()
                first_char_pos = len(lines[next_line]) - len(stripped)
                # Replace only the first colon after the indentation
                lines[next_line] = lines[next_line][:first_char_pos] + lines[next_line][
                    first_char_pos:
                ].replace(":", "", 1)

    return "\n".join(lines)


def is_sphinx_format(docstring):
    style = detect_docstring_style(docstring)
    return style and style == "sphinx"


def is_google_format(docstring):
    style = detect_docstring_style(docstring)
    return style and style == "google"


def convert_google_to_sphinx(docstring: str) -> str:
    """Convert a Google-style docstring to Sphinx/RST format."""
    if not docstring:
        return ""

    # Normalize indentation and excessive blank lines
    docstring = textwrap.dedent(docstring).strip()
    docstring = re.sub(r"\n{3,}", "\n\n", docstring)

    # Handle the case where Args is explicitly set to None with variable whitespace
    args_none_pattern = re.compile(r"Args:\s*\n\s*None\b", re.IGNORECASE)
    if args_none_pattern.search(docstring):
        # Remove the Args: None part and any extra whitespace
        cleaned = args_none_pattern.sub("", docstring).strip()
        # Remove any double newlines that might have been created
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    # Also handle the case where it's on the same line
    if re.search(r"Args:\s*None\b", docstring, re.IGNORECASE):
        return re.sub(r"\s*Args:\s*None\b", "", docstring).strip()

    if not is_google_format(docstring):
        return docstring

    try:
        # Parse the docstring
        parsed_doc = parse(docstring, style=DocstringStyle.GOOGLE)

        # Detect presence of section markers in the raw text
        has_args_marker = bool(
            re.search(r"^\s*Args:\s*$", docstring, flags=re.IGNORECASE | re.MULTILINE)
        )
        has_returns_marker = bool(
            re.search(
                r"^\s*Returns:\s*$", docstring, flags=re.IGNORECASE | re.MULTILINE
            )
        )

        # If parser produced no params/returns but markers exist, fallback to manual
        if not parsed_doc.params and not parsed_doc.returns:
            if has_args_marker or has_returns_marker:
                return _manual_google_to_sphinx(docstring)
            # Otherwise, just return the short description
            return parsed_doc.short_description or ""

        # If parser failed to capture some sections that are present, use manual fallback
        if (has_args_marker and not parsed_doc.params) or (
            has_returns_marker and not parsed_doc.returns
        ):
            return _manual_google_to_sphinx(docstring)

        # Convert to Sphinx style via composer
        parsed_doc.style = DocstringStyle.REST
        result = compose(parsed_doc, style=DocstringStyle.REST)
        return result

    except Exception as e:
        # If parsing fails, return the original docstring
        print(f"Warning: Failed to convert docstring: {e}")
        return _manual_google_to_sphinx(docstring)


def _manual_google_to_sphinx(docstring: str) -> str:
    # Fallback: manually parse Google-style sections into Sphinx format
    text = textwrap.dedent(docstring).strip()

    # Locate section headers
    args_match = re.search(r"^\s*Args:\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
    returns_match = re.search(
        r"^\s*Returns:\s*$", text, flags=re.IGNORECASE | re.MULTILINE
    )

    # Compute spans
    end_of_args_header = args_match.end() if args_match else None
    end_of_returns_header = returns_match.end() if returns_match else None

    # Description is everything before the first header (Args/Returns)
    header_starts = [m.start() for m in [args_match, returns_match] if m]
    description_end = min(header_starts) if header_starts else len(text)
    description = text[:description_end].strip()

    # Extract blocks
    if args_match and returns_match:
        args_block = text[end_of_args_header : returns_match.start()]
    elif args_match:
        args_block = text[end_of_args_header:]
    else:
        args_block = ""

    if returns_match:
        returns_block = text[end_of_returns_header:]
    else:
        returns_block = ""

    # Parse parameters from args_block
    params: list[tuple[str, str]] = []
    current_name: str | None = None
    current_desc_parts: list[str] = []

    for raw_line in args_block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            # Preserve paragraph breaks within a parameter description
            if current_name is not None:
                current_desc_parts.append("")
            continue

        # A new parameter starts when we see "name: desc" with minimal indentation
        m = re.match(r"^\s{0,8}([A-Za-z_][\w]*)\s*:\s*(.*)$", line)
        if m:
            # Flush previous param
            if current_name is not None:
                params.append(
                    (
                        current_name,
                        "\n".join(part for part in current_desc_parts).strip(),
                    )
                )
            current_name = m.group(1)
            first_desc = m.group(2)
            current_desc_parts = [first_desc] if first_desc else []
            continue

        # Continuation lines: must be indented more than the param line
        if current_name is not None:
            # Strip up to 4 spaces of indentation but keep content formatting
            continued = re.sub(r"^\s{0,12}", "", line)
            current_desc_parts.append(continued)

    # Flush last param
    if current_name is not None:
        params.append(
            (current_name, "\n".join(part for part in current_desc_parts).strip())
        )

    # Clean up inline Examples lists to avoid overly long single lines
    cleaned_params: list[tuple[str, str]] = []
    for name, desc in params:
        # If description contains Examples: ..., keep it but ensure a space before Examples
        desc = re.sub(r"\s+Examples:\s*", " Examples: ", desc)
        cleaned_params.append((name, desc.strip()))

    # Parse returns: everything after Returns: header, stripped of leading blank lines
    returns_desc = returns_block.strip()

    # Build Sphinx
    out_parts: list[str] = []
    if description:
        out_parts.append(description)

    for name, desc in cleaned_params:
        out_parts.append(f":param {name}: {desc}")

    if returns_desc:
        out_parts.append(f":returns: {returns_desc}")

    return "\n\n".join(out_parts).strip()


def parse_google_docstring(docstring: str) -> dict[str, Any]:
    """Parse a Google-style docstring and return its constituents.

    Returns a dictionary with keys:
    - description: str (short + long, trimmed)
    - short_description: Optional[str]
    - long_description: Optional[str]
    - params: list of {name, type, description}
    - returns: {type, description, name} or None
    - raises: list of {type, description}
    """
    result: dict[str, Any] = {
        "description": "",
        "short_description": None,
        "long_description": None,
        "params": [],
        "returns": None,
        "raises": [],
    }

    if not docstring:
        return result

    text = textwrap.dedent(docstring).strip()

    try:
        parsed = parse(text, style=DocstringStyle.GOOGLE)
    except Exception:
        parsed = None  # Fallback to manual heuristics below

    if parsed is not None:
        short_desc: str | None = parsed.short_description or None
        long_desc: str | None = parsed.long_description or None

        if short_desc and long_desc:
            description = f"{short_desc}\n\n{long_desc}".strip()
        else:
            description = (short_desc or long_desc or "").strip()

        # Strip any accidental section headers that leaked into description
        header_in_desc = re.search(
            r"^\s*(Args|Parameters|Returns|Yields|Raises):\s*$",
            description,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if header_in_desc:
            description = description[: header_in_desc.start()].strip()

        params = [
            {
                "name": p.arg_name,
                "type": p.type_name or None,
                "description": (p.description or "").strip() or None,
            }
            for p in parsed.params
        ]

        returns = None
        if parsed.returns:
            returns = {
                "type": parsed.returns.type_name or None,
                "description": (parsed.returns.description or "").strip() or None,
                "name": parsed.returns.return_name or None,
            }

        raises_list = []
        if hasattr(parsed, "raises") and parsed.raises:
            for r in parsed.raises:
                raises_list.append(
                    {
                        "type": getattr(r, "type_name", None),
                        "description": (getattr(r, "description", "") or "").strip()
                        or None,
                    }
                )

        result.update(
            {
                "description": description,
                "short_description": short_desc,
                "long_description": long_desc,
                "params": params,
                "returns": returns,
                "raises": raises_list,
            }
        )

        # If parser missed obvious sections but markers exist, attempt manual complement
        has_args_marker = bool(
            re.search(r"^\s*Args:\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
        )
        has_returns_marker = bool(
            re.search(r"^\s*Returns:\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
        )
        if (has_args_marker and not params) or (has_returns_marker and returns is None):
            manual = _manual_extract_google_sections(text)
            if manual["params"] and not params:
                result["params"] = manual["params"]
            if manual["returns"] and returns is None:
                result["returns"] = manual["returns"]

        return result

    # Parser failed: manual extraction
    manual = _manual_extract_google_sections(text)
    result.update(
        {
            "description": manual["description"],
            "short_description": None,
            "long_description": None,
            "params": manual["params"],
            "returns": manual["returns"],
            "raises": [],
        }
    )
    return result


def _manual_extract_google_sections(text: str) -> dict[str, Any]:
    """Manual, tolerant extractor for Google-style Args/Returns into a structured dict."""
    args_match = re.search(r"^\s*Args:\s*$", text, flags=re.IGNORECASE | re.MULTILINE)
    returns_match = re.search(
        r"^\s*Returns:\s*$", text, flags=re.IGNORECASE | re.MULTILINE
    )

    header_starts = [m.start() for m in [args_match, returns_match] if m]
    description_end = min(header_starts) if header_starts else len(text)
    description = text[:description_end].strip()

    end_of_args_header = args_match.end() if args_match else None
    end_of_returns_header = returns_match.end() if returns_match else None

    if args_match and returns_match:
        args_block = text[end_of_args_header : returns_match.start()]
    elif args_match:
        args_block = text[end_of_args_header:]
    else:
        args_block = ""

    returns_block = text[end_of_returns_header:].strip() if returns_match else ""

    # Params
    params: list[dict[str, Any]] = []
    current_name: str | None = None
    current_desc_parts: list[str] = []

    for raw_line in args_block.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current_name is not None:
                current_desc_parts.append("")
            continue

        m = re.match(r"^\s{0,8}([A-Za-z_][\w]*)\s*:\s*(.*)$", line)
        if m:
            if current_name is not None:
                params.append(
                    {
                        "name": current_name,
                        "type": None,
                        "description": (
                            "\n".join(part for part in current_desc_parts).strip()
                            or None
                        ),
                    }
                )
            current_name = m.group(1)
            first_desc = m.group(2)
            current_desc_parts = [first_desc] if first_desc else []
            continue

        if current_name is not None:
            continued = re.sub(r"^\s{0,12}", "", line)
            current_desc_parts.append(continued)

    if current_name is not None:
        params.append(
            {
                "name": current_name,
                "type": None,
                "description": (
                    "\n".join(part for part in current_desc_parts).strip() or None
                ),
            }
        )

    returns: dict[str, Any] | None = None
    if returns_block:
        returns = {
            "type": None,
            "description": returns_block.strip() or None,
            "name": None,
        }

    return {"description": description, "params": params, "returns": returns}


def compose_google_docstring(parts: dict[str, Any]) -> str:
    """Compose a Google-style docstring string from parsed parts.

    Expected keys in parts: description, params (list), returns (dict|None), raises (list)
    """
    lines: list[str] = []

    description = (parts.get("description") or "").strip()
    if description:
        lines.append(description)

    params = parts.get("params") or []
    if params:
        if lines:
            lines.append("")
        lines.append("Args:")
        for param in params:
            name = (param.get("name") or "").strip()
            type_name = (param.get("type") or "").strip() if param.get("type") else ""
            desc = (param.get("description") or "").strip()

            # Google style prefers: name (type): desc  OR name: desc
            if type_name:
                header = f"    {name} ({type_name}):"
            else:
                header = f"    {name}:"

            if not desc:
                lines.append(header)
            else:
                # Escape internal newlines only for parameter descriptions
                escaped_desc = desc.replace("\n", "\\n")
                lines.append(f"{header} {escaped_desc}")

    returns = parts.get("returns")
    if returns:
        ret_type = (
            (returns.get("type") or "").strip() if isinstance(returns, dict) else ""
        )
        ret_name = (
            (returns.get("name") or "").strip() if isinstance(returns, dict) else ""
        )
        ret_desc = (
            (returns.get("description") or "").strip()
            if isinstance(returns, dict)
            else ""
        )

        if lines:
            lines.append("")
        lines.append("Returns:")

        # Preferred Google format: type: description  OR name (type): description
        if ret_name and ret_type:
            first_line = f"    {ret_name} ({ret_type}):"
        elif ret_name:
            first_line = f"    {ret_name}:"
        elif ret_type:
            first_line = f"    {ret_type}:"
        else:
            first_line = "    "  # indent baseline, description will follow

        if not ret_desc:
            lines.append(first_line.rstrip())
        else:
            desc_lines = ret_desc.splitlines() or [""]
            if first_line.strip():
                lines.append(f"{first_line} {desc_lines[0]}")
            else:
                lines.append(f"    {desc_lines[0]}")
            for extra in desc_lines[1:]:
                lines.append(f"        {extra}")

    raises = parts.get("raises") or []
    if raises:
        if lines:
            lines.append("")
        lines.append("Raises:")
        for r in raises:
            r_type = (r.get("type") or "").strip()
            r_desc = (r.get("description") or "").strip()
            if not r_type and not r_desc:
                continue
            if r_desc:
                first, *rest = r_desc.splitlines()
                lines.append(f"    {r_type}: {first}" if r_type else f"    {first}")
                for extra in rest:
                    lines.append(f"        {extra}")
            else:
                lines.append(f"    {r_type}:")

    return "\n".join(lines).rstrip()
