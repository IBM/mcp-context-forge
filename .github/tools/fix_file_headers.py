#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A script to check and enforce standardized license and authorship headers.

Location: ./.github/tools/fix_file_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Arnav Bhattacharya, Mihai Criveti

This script scans Python files to ensure they contain a standard header
with copyright, license, and author information. By default, it runs in
check mode (dry run) and requires explicit flags to modify files.

Operating modes:
- Check (default): Reports files with missing or incorrect headers without modifying
- Fix: Modifies headers for specific files/directories (requires --fix and --path)
- Fix-All: Automatically corrects headers of all python files (requires --fix-all)
- Interactive: Prompts for confirmation before fixing each file (requires --interactive)

The script is designed to be run from the command line, either directly
or via the provided Makefile targets. It uses Python's AST module for safe
parsing and modification of Python source files.

Attributes:
    PROJECT_ROOT (Path): The root directory of the project.
    INCLUDE_DIRS (List[str]): Directories to include in the scan.
    EXCLUDE_DIRS (Set[str]): Directories to exclude from the scan.
    COPYRIGHT_YEAR (int): The current year for copyright notices.
    AUTHORS (str): Default author name(s) for headers.
    LICENSE (str): The project's license identifier.

Examples:
    Check all files (default behavior - dry run):
        >>> # python3 .github/tools/fix_file_headers.py

    Check with diff preview:
        >>> # python3 .github/tools/fix_file_headers.py --show-diff

    Fix all files (requires explicit flag):
        >>> # python3 .github/tools/fix_file_headers.py --fix-all

    Fix a specific file or directory:
        >>> # python3 .github/tools/fix_file_headers.py --fix --path ./mcpgateway/main.py

    Fix with specific authors:
        >>> # python3 .github/tools/fix_file_headers.py --fix --path ./mcpgateway/main.py --authors "John Doe, Jane Smith"

    Interactive mode:
        >>> # python3 .github/tools/fix_file_headers.py --interactive

Note:
    This script will NOT modify files unless explicitly told to with --fix, --fix-all,
    or --interactive flags. Always commit your changes before running in fix mode to
    allow easy rollback if needed.

Testing:
    Run doctests with: python -m doctest .github/tools/fix_file_headers.py -v
"""

# Standard
import argparse
import ast
from datetime import datetime
import difflib
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

# Configuration constants
PROJECT_ROOT: Path = Path(__file__).parent.parent.parent.resolve()
INCLUDE_DIRS: List[str] = ["mcpgateway", "tests"]
EXCLUDE_DIRS: Set[str] = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".idea", ".vscode", "node_modules", ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
COPYRIGHT_YEAR: int = datetime.now().year
AUTHORS: str = "Mihai Criveti"
LICENSE: str = "Apache-2.0"

# Constants for header validation
SHEBANG_LINE: str = "#!/usr/bin/env python3"
ENCODING_LINE: str = "# -*- coding: utf-8 -*-"
HEADER_FIELDS: List[str] = ["Location", "Copyright", "SPDX-License-Identifier", "Authors"]


def is_executable(file_path: Path) -> bool:
    """Check if a file has executable permissions.

    Args:
        file_path: The path to check.

    Returns:
        bool: True if the file is executable, False otherwise.

    Examples:
        >>> from tempfile import NamedTemporaryFile
        >>> import os
        >>> with NamedTemporaryFile(mode='w', delete=False) as tmp:
        ...     tmp_path = Path(tmp.name)
        >>> is_executable(tmp_path)
        False
        >>> os.chmod(tmp_path, 0o755)
        >>> is_executable(tmp_path)
        True
        >>> tmp_path.unlink()
    """
    return os.access(file_path, os.X_OK)


def validate_authors(authors: str) -> bool:
    """Validate that the authors string is properly formatted.

    Args:
        authors: A string containing author names, typically comma-separated.

    Returns:
        bool: True if the authors string is valid, False otherwise.

    Examples:
        >>> validate_authors("John Doe")
        True
        >>> validate_authors("John Doe, Jane Smith")
        True
        >>> validate_authors("")
        False
        >>> validate_authors("   ")
        False
        >>> validate_authors("John@Doe")
        True
    """
    return bool(authors and authors.strip())


def validate_path(path: Path, require_in_project: bool = True) -> Tuple[bool, Optional[str]]:
    """Validate that a path is safe to process.

    Args:
        path: The path to validate.
        require_in_project: Whether to require the path be within PROJECT_ROOT.

    Returns:
        Tuple[bool, Optional[str]]: A tuple of (is_valid, error_message).
            If is_valid is True, error_message is None.

    Examples:
        >>> # Test with a file that exists (this script itself)
        >>> p = Path(__file__)
        >>> valid, msg = validate_path(p)
        >>> valid
        True
        >>> msg is None
        True

        >>> # Test with non-existent file
        >>> p = PROJECT_ROOT / "nonexistent_test_file_12345.py"
        >>> valid, msg = validate_path(p)
        >>> valid
        False
        >>> "does not exist" in msg
        True

        >>> p = Path("/etc/passwd")
        >>> valid, msg = validate_path(p)
        >>> valid
        False
        >>> "outside project root" in msg
        True
    """
    if not path.exists():
        return False, f"Path does not exist: {path}"

    if require_in_project:
        try:
            path.relative_to(PROJECT_ROOT)
        except ValueError:
            return False, f"Path is outside project root: {path}"

    return True, None


def get_header_template(relative_path: str, authors: str = AUTHORS, include_shebang: bool = True, include_encoding: bool = True) -> str:
    """Generate the full, standardized header text.

    Args:
        relative_path: The relative path from project root to the file.
        authors: The author name(s) to include in the header.
        include_shebang: Whether to include the shebang line.
        include_encoding: Whether to include the encoding line.

    Returns:
        str: The complete header template with proper formatting.

    Examples:
        >>> header = get_header_template("test/example.py", "John Doe")
        >>> "#!/usr/bin/env python3" in header
        True
        >>> "Location: ./test/example.py" in header
        True
        >>> "Authors: John Doe" in header
        True
        >>> f"Copyright {COPYRIGHT_YEAR}" in header
        True

        >>> header_no_shebang = get_header_template("test/example.py", "John Doe", include_shebang=False)
        >>> "#!/usr/bin/env python3" in header_no_shebang
        False
        >>> "# -*- coding: utf-8 -*-" in header_no_shebang
        True
    """
    lines = []

    if include_shebang:
        lines.append(SHEBANG_LINE)
    if include_encoding:
        lines.append(ENCODING_LINE)

    lines.append(f'''"""Module Description.
Location: ./{relative_path}
Copyright {COPYRIGHT_YEAR}
SPDX-License-Identifier: {LICENSE}
Authors: {authors}

Module documentation...
"""''')

    return '\n'.join(lines)


def _write_file(file_path: Path, content: str) -> None:
    """Write content to a file with proper encoding and error handling.

    Args:
        file_path: The path to the file to write.
        content: The content to write to the file.

    Raises:
        IOError: If the file cannot be written.

    Examples:
        >>> from tempfile import NamedTemporaryFile
        >>> with NamedTemporaryFile(mode='w', delete=False) as tmp:
        ...     tmp_path = Path(tmp.name)
        >>> _write_file(tmp_path, "test content")
        >>> tmp_path.read_text()
        'test content'
        >>> tmp_path.unlink()
    """
    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        raise IOError(f"Failed to write file {file_path}: {e}")


def find_python_files(base_path: Optional[Path] = None) -> Generator[Path, None, None]:
    """Yield all Python files in the project, respecting include/exclude rules.

    Args:
        base_path: Optional specific path to search. If None, searches INCLUDE_DIRS.

    Yields:
        Path: Paths to Python files found in the search directories.

    Examples:
        >>> # Find files in a test directory
        >>> test_dir = PROJECT_ROOT / "test_dir"
        >>> test_dir.mkdir(exist_ok=True)
        >>> (test_dir / "test.py").write_text("# test")
        6
        >>> (test_dir / "test.txt").write_text("not python")
        10
        >>> files = list(find_python_files(test_dir))
        >>> len(files) == 1
        True
        >>> files[0].name == "test.py"
        True
        >>> # Cleanup
        >>> (test_dir / "test.py").unlink()
        >>> (test_dir / "test.txt").unlink()
        >>> test_dir.rmdir()
    """
    search_paths: List[Path] = [base_path] if base_path else [PROJECT_ROOT / d for d in INCLUDE_DIRS]

    for search_dir in search_paths:
        if not search_dir.exists():
            continue

        if search_dir.is_file() and search_dir.suffix == ".py":
            yield search_dir
            continue

        if not search_dir.is_dir():
            continue

        for file_path in search_dir.rglob("*.py"):
            try:
                relative_to_project = file_path.relative_to(PROJECT_ROOT)
                # Check if any part of the path is in EXCLUDE_DIRS
                if not any(ex_dir in relative_to_project.parts for ex_dir in EXCLUDE_DIRS):
                    yield file_path
            except ValueError:
                # File is outside PROJECT_ROOT, skip it
                continue


def extract_header_info(source_code: str, docstring: str) -> Dict[str, Optional[str]]:
    """Extract existing header information from a docstring.

    Args:
        source_code: The complete source code of the file.
        docstring: The module docstring to parse.

    Returns:
        Dict[str, Optional[str]]: A dictionary mapping header field names to their values.

    Examples:
        >>> docstring = '''Module description.
        ... Location: ./test/file.py
        ... Copyright 2025
        ... SPDX-License-Identifier: Apache-2.0
        ... Authors: John Doe
        ...
        ... More documentation.'''
        >>> info = extract_header_info("", docstring)
        >>> info["Location"]
        'Location: ./test/file.py'
        >>> info["Authors"]
        'Authors: John Doe'
        >>> "Copyright" in info["Copyright"]
        True
    """
    # source_code parameter is kept for API compatibility but not used in current implementation
    _ = source_code

    header_info: Dict[str, Optional[str]] = {"Location": None, "Copyright": None, "SPDX-License-Identifier": None, "Authors": None}

    for line in docstring.splitlines():
        line = line.strip()
        if line.startswith("Location:"):
            header_info["Location"] = line
        elif line.startswith("Copyright"):
            header_info["Copyright"] = line
        elif line.startswith("SPDX-License-Identifier:"):
            header_info["SPDX-License-Identifier"] = line
        elif line.startswith("Authors:"):
            header_info["Authors"] = line

    return header_info


def generate_diff(original: str, modified: str, filename: str) -> str:
    r"""Generate a unified diff between original and modified content.

    Args:
        original: The original file content.
        modified: The modified file content.
        filename: The name of the file for the diff header.

    Returns:
        str: A unified diff string.

    Examples:
        >>> original = "line1\nline2\n"
        >>> modified = "line1\nline2 modified\n"
        >>> diff = generate_diff(original, modified, "test.py")
        >>> "@@" in diff
        True
        >>> "+line2 modified" in diff
        True
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(original_lines, modified_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="")

    return "\n".join(diff)


def show_file_lines(file_path: Path, num_lines: int = 10) -> str:
    """Show the first few lines of a file for debugging.

    Args:
        file_path: The path to the file.
        num_lines: Number of lines to show.

    Returns:
        str: A formatted string showing the first lines of the file.
    """
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
        result = []
        for i, line in enumerate(lines[:num_lines], 1):
            result.append(f"{i:3d}: {repr(line)}")
        if len(lines) > num_lines:
            result.append(f"     ... ({len(lines) - num_lines} more lines)")
        return "\n".join(result)
    except Exception as e:
        return f"Error reading file: {e}"


def process_file(file_path: Path, mode: str, authors: str, show_diff: bool = False, debug: bool = False,
                 require_shebang: Optional[bool] = None, require_encoding: bool = True) -> Optional[Dict[str, Any]]:
    """Check a single file and optionally fix its header.

    Args:
        file_path: The path to the Python file to process.
        mode: The processing mode ("check", "fix-all", "fix", or "interactive").
        authors: The author name(s) to use in headers.
        show_diff: Whether to show a diff preview in check mode.
        debug: Whether to show debug information about file contents.
        require_shebang: Whether to require shebang line. If None, only required for executable files.
        require_encoding: Whether to require encoding line.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing:
            - 'file': The relative path to the file
            - 'issues': List of header issues found
            - 'fixed': Whether the file was fixed (optional)
            - 'skipped': Whether the fix was skipped in interactive mode (optional)
            - 'diff': The diff preview if show_diff is True (optional)
            - 'debug': Debug information if debug is True (optional)
        Returns None if no issues were found.

    Examples:
        >>> from tempfile import NamedTemporaryFile
        >>> with NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
        ...     tmp.write('print("test")')
        ...     tmp_path = Path(tmp.name)
        13
        >>> result = process_file(tmp_path, "check", "Test Author")
        >>> result is not None
        True
        >>> "Missing encoding line" in result['issues']
        True
        >>> tmp_path.unlink()
    """
    try:
        relative_path_str = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        relative_path_str = str(file_path)

    try:
        source_code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return {"file": relative_path_str, "issues": [f"Syntax error: {e}"]}
    except Exception as e:
        return {"file": relative_path_str, "issues": [f"Error reading/parsing file: {e}"]}

    issues: List[str] = []
    lines = source_code.splitlines()

    # Determine if shebang is required
    file_is_executable = is_executable(file_path)
    shebang_required = require_shebang if require_shebang is not None else file_is_executable

    # Check for shebang and encoding
    has_shebang = bool(lines and lines[0].strip() == SHEBANG_LINE)
    has_encoding = len(lines) > 1 and lines[1].strip() == ENCODING_LINE

    # Handle encoding on first line if no shebang
    if not has_shebang and lines and lines[0].strip() == ENCODING_LINE:
        has_encoding = True

    if shebang_required and not has_shebang:
        issues.append("Missing shebang line (file is executable)" if file_is_executable else "Missing shebang line")

    if require_encoding and not has_encoding:
        issues.append("Missing encoding line")

    # Get module docstring
    docstring_node = ast.get_docstring(tree, clean=False)
    module_body = tree.body
    new_source_code = None

    if docstring_node is not None:
        # Check for required header fields
        location_match = re.search(r"^Location: \./(.*)$", docstring_node, re.MULTILINE)
        if not location_match:
            issues.append("Missing 'Location' line")
        elif location_match.group(1) != relative_path_str:
            issues.append(f"Incorrect 'Location' line: expected './{relative_path_str}', found './{location_match.group(1)}'")

        if f"Copyright {COPYRIGHT_YEAR}" not in docstring_node:
            issues.append("Missing 'Copyright' line")

        if f"SPDX-License-Identifier: {LICENSE}" not in docstring_node:
            issues.append("Missing 'SPDX-License-Identifier' line")

        if not re.search(r"^Authors: ", docstring_node, re.MULTILINE):
            issues.append("Missing 'Authors' line")

        if not issues:
            return None

        # Generate new source code for diff preview or actual fixing
        if mode in ["fix-all", "fix", "interactive"] or show_diff:
            # Extract the raw docstring from source
            if module_body and isinstance(module_body[0], ast.Expr):
                docstring_expr_node = module_body[0]
                raw_docstring = ast.get_source_segment(source_code, docstring_expr_node)

                if raw_docstring:
                    # Determine quote style
                    quotes = '"""' if raw_docstring.startswith('"""') else "'''"
                    inner_content = raw_docstring.strip(quotes)

                    # Extract existing header fields
                    existing_header_fields = extract_header_info(source_code, inner_content)

                    # Split docstring into lines for analysis
                    docstring_lines = inner_content.strip().splitlines()

                    # Separate the docstring into header and content parts
                    content_lines = []
                    in_header_section = False

                    for i, line in enumerate(docstring_lines):
                        line_stripped = line.strip()

                        # Check if this line is a header field
                        is_header_field = (any(line_stripped.startswith(field + ":") for field in HEADER_FIELDS) or
                                         line_stripped.startswith("Copyright"))

                        if is_header_field:
                            in_header_section = True
                        elif in_header_section and not line_stripped:
                            # Empty line might separate header from content - continue checking
                            continue
                        elif in_header_section and line_stripped and not is_header_field:
                            # Found content after header section - this and everything after is content
                            content_lines.extend(docstring_lines[i:])
                            break
                        elif not in_header_section and line_stripped:
                            # Content before any header section (like module descriptions)
                            # Look ahead to see if there are headers following
                            has_headers_following = any(
                                any(future_line.strip().startswith(field + ":") for field in HEADER_FIELDS) or
                                future_line.strip().startswith("Copyright")
                                for future_line in docstring_lines[i+1:]
                            )
                            if has_headers_following:
                                # This is content, headers follow later
                                content_lines.append(line)
                            else:
                                # No headers following, this is regular content
                                content_lines.extend(docstring_lines[i:])
                                break

                    # Build new header
                    new_header_lines = []
                    # Always use correct location path
                    new_header_lines.append(f"Location: ./{relative_path_str}")
                    new_header_lines.append(existing_header_fields.get("Copyright") or f"Copyright {COPYRIGHT_YEAR}")
                    new_header_lines.append(existing_header_fields.get("SPDX-License-Identifier") or f"SPDX-License-Identifier: {LICENSE}")
                    # Preserve existing Authors field if it exists, otherwise use the provided authors
                    new_header_lines.append(existing_header_fields.get("Authors") or f"Authors: {authors}")

                    # Reconstruct docstring with preserved content
                    new_inner_content = "\n".join(new_header_lines)
                    if content_lines:
                        content_str = "\n".join(content_lines)
                        new_inner_content += "\n\n" + content_str

                    # Ensure proper ending with newline before closing quotes
                    if not new_inner_content.endswith('\n'):
                        new_inner_content += '\n'

                    new_docstring = f"{quotes}{new_inner_content}{quotes}"

                    # Prepare source with appropriate headers
                    header_lines = []
                    if shebang_required:
                        header_lines.append(SHEBANG_LINE)
                    if require_encoding:
                        header_lines.append(ENCODING_LINE)

                    if header_lines:
                        shebang_lines = "\n".join(header_lines) + "\n"
                    else:
                        shebang_lines = ""

                    # Remove existing shebang/encoding if present
                    start_line = 0
                    if has_shebang:
                        start_line += 1
                    if has_encoding and len(lines) > start_line and lines[start_line].strip() == ENCODING_LINE:
                        start_line += 1

                    source_without_headers = "\n".join(lines[start_line:]) if start_line < len(lines) else ""

                    # Replace the docstring
                    new_source_code = source_without_headers.replace(raw_docstring, new_docstring, 1)
                    new_source_code = shebang_lines + new_source_code

    else:
        # No docstring found
        issues.append("No docstring found")

        # Generate new source code for diff preview or actual fixing
        if mode in ["fix-all", "fix", "interactive"] or show_diff:
            # Create new header
            new_header = get_header_template(
                relative_path_str,
                authors=authors,
                include_shebang=shebang_required,
                include_encoding=require_encoding
            )

            # Remove existing shebang/encoding if present
            start_line = 0
            if has_shebang:
                start_line += 1
            if has_encoding and len(lines) > start_line and lines[start_line].strip() == ENCODING_LINE:
                start_line += 1

            remaining_content = "\n".join(lines[start_line:]) if start_line < len(lines) else source_code
            new_source_code = new_header + "\n" + remaining_content

    # Handle the result
    result: Dict[str, Any] = {"file": relative_path_str, "issues": issues}

    if debug:
        result["debug"] = {
            "executable": file_is_executable,
            "has_shebang": has_shebang,
            "has_encoding": has_encoding,
            "first_lines": show_file_lines(file_path, 5)
        }

    if show_diff and new_source_code and new_source_code != source_code:
        result["diff"] = generate_diff(source_code, new_source_code, relative_path_str)

    if new_source_code and new_source_code != source_code and mode != "check":
        if mode == "interactive":
            print(f"\n📄 File: {relative_path_str}")
            print(f"   Issues: {', '.join(issues)}")
            if debug:
                print(f"   Executable: {file_is_executable}")
                print("   First lines:")
                print("   " + "\n   ".join(show_file_lines(file_path, 5).split("\n")))
            if show_diff:
                print("\n--- Proposed changes ---")
                print(result.get("diff", ""))
            confirm = input("\n  Apply changes? (y/n): ").lower().strip()
            if confirm != "y":
                result["fixed"] = False
                result["skipped"] = True
                return result

        try:
            _write_file(file_path, new_source_code)
            result["fixed"] = True
        except IOError as e:
            result["issues"].append(f"Failed to write file: {e}")
            result["fixed"] = False
    else:
        result["fixed"] = False

    return result if issues else None


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Optional list of arguments. If None, uses sys.argv[1:].

    Returns:
        argparse.Namespace: Parsed command line arguments.

    Examples:
        >>> args = parse_arguments(["--check"])
        >>> args.check
        True
        >>> args.fix_all
        False

        >>> args = parse_arguments(["--fix", "--path", "test.py", "--authors", "John Doe"])
        >>> args.fix
        True
        >>> args.path
        'test.py'
        >>> args.authors
        'John Doe'

        >>> # Default behavior with no args
        >>> args = parse_arguments([])
        >>> args.check
        False
        >>> args.fix
        False
        >>> args.fix_all
        False
    """
    parser = argparse.ArgumentParser(
        description="Check and fix file headers in Python source files. " "By default, runs in check mode (dry run).",
        epilog="Examples:\n"
        "  %(prog)s                    # Check all files (default)\n"
        "  %(prog)s --fix-all          # Fix all files\n"
        "  %(prog)s --fix --path file.py  # Fix specific file\n"
        "  %(prog)s --interactive      # Fix with prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("files", nargs="*", help="Files to process (usually passed by pre-commit).")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--check", action="store_true", help="Dry run: check files but do not make changes (default behavior).")
    mode_group.add_argument("--fix", action="store_true", help="Fix headers in files specified by --path. Requires --path.")
    mode_group.add_argument("--fix-all", action="store_true", help="Automatically fix all incorrect headers in the project.")
    mode_group.add_argument("--interactive", action="store_true", help="Interactively review and apply fixes.")

    parser.add_argument("--path", type=str, help="Specify a file or directory to process. Required with --fix.")
    parser.add_argument("--authors", type=str, default=AUTHORS, help=f"Specify the author name(s) for new headers. Default: {AUTHORS}")
    parser.add_argument("--show-diff", action="store_true", help="Show diff preview of changes in check mode.")
    parser.add_argument("--debug", action="store_true", help="Show debug information about file contents.")

    # Header configuration options
    header_group = parser.add_argument_group("header configuration")
    header_group.add_argument("--require-shebang", choices=["always", "never", "auto"], default="auto",
                              help="Require shebang line: 'always', 'never', or 'auto' (only for executable files). Default: auto")
    header_group.add_argument("--require-encoding", action="store_true", default=True,
                              help="Require encoding line. Default: True")
    header_group.add_argument("--no-encoding", action="store_false", dest="require_encoding",
                              help="Don't require encoding line.")
    header_group.add_argument("--copyright-year", type=int, default=COPYRIGHT_YEAR,
                              help=f"Copyright year to use. Default: {COPYRIGHT_YEAR}")
    header_group.add_argument("--license", type=str, default=LICENSE,
                              help=f"License identifier to use. Default: {LICENSE}")

    return parser.parse_args(argv)


def determine_mode(args: argparse.Namespace) -> str:
    """Determine the operating mode from parsed arguments.

    Args:
        args: Parsed command line arguments.

    Returns:
        str: The mode to operate in ("check", "fix-all", "fix", or "interactive").

    Examples:
        >>> from argparse import Namespace
        >>> args = Namespace(files=[], check=True, fix_all=False, interactive=False, path=None, fix=False)
        >>> determine_mode(args)
        'check'

        >>> args = Namespace(files=[], check=False, fix_all=True, interactive=False, path=None, fix=False)
        >>> determine_mode(args)
        'fix-all'

        >>> args = Namespace(files=[], check=False, fix_all=False, interactive=False, path="test.py", fix=True)
        >>> determine_mode(args)
        'fix'

        >>> # Default behavior with no flags
        >>> args = Namespace(files=[], check=False, fix_all=False, interactive=False, path=None, fix=False)
        >>> determine_mode(args)
        'check'
    """
    # Check if any modification mode is explicitly requested
    if args.fix_all:
        return "fix-all"
    if args.interactive:
        return "interactive"
    if args.fix and args.path:
        return "fix"
    if args.check:
        return "check"
    # Default to check mode if no flags specified
    return "check"


def collect_files_to_process(args: argparse.Namespace) -> List[Path]:
    """Collect all files that need to be processed based on arguments.

    Args:
        args: Parsed command line arguments.

    Returns:
        List[Path]: List of file paths to process.

    Raises:
        SystemExit: If an invalid path is specified.

    Examples:
        >>> from argparse import Namespace
        >>> args = Namespace(files=[], path=None)
        >>> files = collect_files_to_process(args)
        >>> isinstance(files, list)
        True
    """
    files_to_process: List[Path] = []

    if args.files:
        files_to_process = [Path(f) for f in args.files]
    elif args.path:
        target_path = Path(args.path)

        # Convert to absolute path if relative
        if not target_path.is_absolute():
            target_path = PROJECT_ROOT / target_path

        # Validate the path
        valid, error_msg = validate_path(target_path)
        if not valid:
            print(f"Error: {error_msg}", file=sys.stderr)
            sys.exit(1)

        if target_path.is_file() and target_path.suffix == ".py":
            files_to_process = [target_path]
        elif target_path.is_dir():
            files_to_process = list(find_python_files(target_path))
        else:
            print(f"Error: Path '{args.path}' is not a valid Python file or directory.", file=sys.stderr)
            sys.exit(1)
    else:
        files_to_process = list(find_python_files())

    return files_to_process


def print_results(issues_found: List[Dict[str, Any]], mode: str, modified_count: int) -> None:
    """Print the results of the header checking/fixing process.

    Args:
        issues_found: List of dictionaries containing file issues and status.
        mode: The mode that was used ("check", "fix-all", etc.).
        modified_count: Number of files that were modified.

    Examples:
        >>> issues = [{"file": "test.py", "issues": ["Missing header"], "fixed": True}]
        >>> import sys
        >>> from io import StringIO
        >>> old_stderr = sys.stderr
        >>> sys.stderr = StringIO()
        >>> try:
        ...     print_results(issues, "fix-all", 1)
        ...     output = sys.stderr.getvalue()
        ...     "✅ Fixed: test.py" in output
        ... finally:
        ...     sys.stderr = old_stderr
        True
    """
    if not issues_found:
        print("All Python file headers are correct. ✨", file=sys.stdout)
        return

    print("\n--- Header Issues Found ---", file=sys.stderr)

    for issue_info in issues_found:
        file_name = issue_info["file"]
        issues_list = issue_info["issues"]
        fixed_status = issue_info.get("fixed", False)
        skipped_status = issue_info.get("skipped", False)

        if fixed_status:
            print(f"✅ Fixed: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)
        elif skipped_status:
            print(f"⚠️  Skipped: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)
        else:
            print(f"❌ Needs Fix: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)

        # Show debug info if available
        if "debug" in issue_info:
            debug = issue_info["debug"]
            print("   Debug info:", file=sys.stderr)
            print(f"     Executable: {debug['executable']}", file=sys.stderr)
            print(f"     Has shebang: {debug['has_shebang']}", file=sys.stderr)
            print(f"     Has encoding: {debug['has_encoding']}", file=sys.stderr)

        # Show diff if available
        if "diff" in issue_info and mode == "check":
            print(f"\n--- Diff preview for {file_name} ---", file=sys.stderr)
            print(issue_info["diff"], file=sys.stderr)

    # Print helpful messages based on mode
    if mode == "check":
        print("\nTo fix these headers, run: make fix-all-headers", file=sys.stderr)
        print("Or add to your pre-commit config with '--fix-all' argument.", file=sys.stderr)
    elif mode == "interactive":
        print("\nSome files may have been skipped in interactive mode.", file=sys.stderr)
        print("To fix all remaining headers, run: make fix-all-headers", file=sys.stderr)
    elif modified_count > 0:
        print(f"\nSuccessfully fixed {modified_count} file(s). " f"Please re-stage and commit.", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> None:
    """Parse arguments and run the script.

    Args:
        argv: Optional list of command line arguments. If None, uses sys.argv[1:].

    Raises:
        SystemExit: With code 0 on success, 1 if issues were found.

    Examples:
        >>> # Test with no arguments (check mode by default)
        >>> import sys
        >>> from io import StringIO
        >>> old_stdout = sys.stdout
        >>> sys.stdout = StringIO()
        >>> try:
        ...     main([])  # Should run in check mode
        ... except SystemExit as e:
        ...     sys.stdout = old_stdout
        ...     e.code in (0, 1)
        True

        >>> # Test with explicit fix mode on non-existent file
        >>> try:
        ...     main(["--fix", "--path", "nonexistent.py"])
        ... except SystemExit as e:
        ...     e.code == 1
        True
    """
    global COPYRIGHT_YEAR, LICENSE

    args = parse_arguments(argv)

    # Update global config from arguments
    COPYRIGHT_YEAR = args.copyright_year
    LICENSE = args.license

    # Validate --fix requires --path
    if args.fix and not args.path:
        print("Error: --fix requires --path to specify which file or directory to fix.", file=sys.stderr)
        print("Usage: fix_file_headers.py --fix --path <file_or_directory>", file=sys.stderr)
        sys.exit(1)

    mode = determine_mode(args)

    # Validate authors
    if not validate_authors(args.authors):
        print("Error: Invalid authors string. Authors cannot be empty.", file=sys.stderr)
        sys.exit(1)

    # Collect files to process
    files_to_process = collect_files_to_process(args)

    if not files_to_process:
        print("No Python files found to process.", file=sys.stdout)
        sys.exit(0)

    # Show mode information
    if mode == "check":
        print("🔍 Running in CHECK mode (dry run). No files will be modified.")
        if args.show_diff:
            print("   Diff preview enabled.")
        if args.debug:
            print("   Debug mode enabled.")
    elif mode == "fix":
        print(f"🔧 Running in FIX mode for: {args.path}")
        print("   Files WILL be modified!")
    elif mode == "fix-all":
        print("🔧 Running in FIX-ALL mode.")
        print("   ALL files with incorrect headers WILL be modified!")
    elif mode == "interactive":
        print("💬 Running in INTERACTIVE mode.")
        print("   You will be prompted before each change.")

    # Determine shebang requirement
    require_shebang = None
    if args.require_shebang == "always":
        require_shebang = True
    elif args.require_shebang == "never":
        require_shebang = False
    # else: auto mode, require_shebang remains None

    # Process files
    issues_found_in_files: List[Dict[str, Any]] = []
    modified_files_count = 0

    for file_path in files_to_process:
        result = process_file(
            file_path,
            mode,
            args.authors,
            show_diff=args.show_diff,
            debug=args.debug,
            require_shebang=require_shebang,
            require_encoding=args.require_encoding
        )
        if result:
            issues_found_in_files.append(result)
            if result.get("fixed", False):
                modified_files_count += 1

    # Print results
    print_results(issues_found_in_files, mode, modified_files_count)

    # Exit with appropriate code
    if issues_found_in_files:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
