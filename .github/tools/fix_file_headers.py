#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A script to check and enforce standardized license and authorship headers.
Location: ./.github/tools/fix_file_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Arnav Bhattacharya

This script scans Python files to ensure they contain a standard header
with copyright, license, and author information. It can run in several modes:
- Check: Reports files with missing or incorrect headers.
- Fix-All: Automatically corrects headers of all python files.
- Fix: Corrects headers for specified files or directories. The path is required for this mode.
- Interactive: Prompts for confirmation before fixing each file.

The script is designed to be run from the command line, either directly
or via the provided Makefile targets.

Usage:
  # Check all files (dry run)
  python3 .github/tools/fix_file_headers.py --check

  # Automatically fix all files
  python3 .github/tools/fix_file_headers.py --fix-all

  # Fix a specific file or directory
  python3 .github/tools/fix_file_headers.py --fix --path ./mcpgateway/main.py

  # Fix a file and specify the authors
  python3 .github/tools/fix_file_headers.py --fix --path ./mcpgateway/main.py --authors "First Author, Second Author"
"""

import argparse
import ast
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
INCLUDE_DIRS = ["mcpgateway", "tests"]
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "build", "dist", ".idea", ".vscode"
}
COPYRIGHT_YEAR = datetime.now().year
AUTHORS = "Mihai Criveti"
LICENSE = "Apache-2.0"

def get_header_template(relative_path: str, authors: str = "Mihai Criveti") -> str:
    """
    Generates the full, standardized header text including shebangs.
    """
    return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module Description.
Location: ./{relative_path}
Copyright {COPYRIGHT_YEAR}
SPDX-License-Identifier: {LICENSE}
Authors: {authors}

Module documentation...
"""'''

def _write_file(file_path: Path, content: str):
    """Writes content to a file, ensuring utf-8 encoding."""
    file_path.write_text(content, "utf-8")

def find_python_files(base_path: Optional[Path] = None):
    """Yields all Python files in the project, respecting include/exclude rules."""
    search_paths = [base_path] if base_path else [PROJECT_ROOT / d for d in INCLUDE_DIRS]

    for search_dir in search_paths:
        if not search_dir.is_dir():
            if search_dir.is_file() and search_dir.suffix == ".py":
                yield search_dir
            continue

        for file_path in search_dir.rglob("*.py"):
            try:
                relative_to_project = file_path.relative_to(PROJECT_ROOT)
                if not any(ex_dir in relative_to_project.parts for ex_dir in EXCLUDE_DIRS):
                    yield file_path
            except ValueError:
                continue


def process_file(file_path: Path, mode: str, authors: str) -> Optional[Dict[str, Any]]:
    """
    Checks a single file and, if necessary, fixes its header.
    Returns a dictionary of issues if problems are found, None otherwise.
    The dictionary includes 'file' (relative path) and 'issues' (list of strings).
    """
    relative_path_str = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    try:
        source_code = file_path.read_text("utf-8")
        tree = ast.parse(source_code)
    except Exception as e:
        return {'file': relative_path_str, 'issues': [f"Error parsing file: {e}"]}

    issues = []

    lines = source_code.splitlines()
    has_shebang = lines and lines[0].strip() == '#!/usr/bin/env python3'
    has_encoding = len(lines) > 1 and lines[1].strip() == '# -*- coding: utf-8 -*-'

    if not has_shebang or not has_encoding:
        issues.append("Missing 'Shebang' lines")

    docstring_node = ast.get_docstring(tree, clean=False)
    module_body = tree.body
    new_source_code = None

    if docstring_node is not None:
        if not re.search(r"^Location: \./(.*)$", docstring_node, re.MULTILINE):
            issues.append("Missing 'Location' line")
        if f"Copyright {COPYRIGHT_YEAR}" not in docstring_node:
            issues.append("Missing 'Copyright' line")
        if f"SPDX-License-Identifier: {LICENSE}" not in docstring_node:
            issues.append("Missing 'SPDX-License-Identifier' line")
        if not re.search(r"^Authors: ", docstring_node, re.MULTILINE):
            issues.append("Missing 'Authors' line")

        if not issues:
            return None

        if mode in ["fix-all", "fix", "interactive"]:
            docstring_expr_node = module_body[0]
            raw_docstring = ast.get_source_segment(source_code, docstring_expr_node)
            quotes = '"""' if raw_docstring and raw_docstring.startswith('"""') else "'''"
            inner_content = raw_docstring.strip(quotes) if raw_docstring else ""

            existing_header_fields = {}
            docstring_body_lines = []

            in_header_block = True
            for line in inner_content.strip().splitlines():
                if line.startswith("Location:"):
                    existing_header_fields["Location"] = line.strip()
                elif line.startswith("Copyright"):
                    existing_header_fields["Copyright"] = line.strip()
                elif line.startswith("SPDX-License-Identifier:"):
                    existing_header_fields["SPDX-License-Identifier"] = line.strip()
                elif line.startswith("Authors:"):
                    existing_header_fields["Authors"] = line.strip()
                elif not line.strip() and in_header_block:
                    pass
                else:
                    in_header_block = False
                    docstring_body_lines.append(line)

            new_header_lines = []
            new_header_lines.append(existing_header_fields.get("Location", f"Location: ./{relative_path_str}"))
            new_header_lines.append(existing_header_fields.get("Copyright", f"Copyright {COPYRIGHT_YEAR}"))
            new_header_lines.append(existing_header_fields.get("SPDX-License-Identifier", f"SPDX-License-Identifier: {LICENSE}"))
            new_header_lines.append(f"Authors: {authors}")

            new_inner_content = "\n".join(new_header_lines)
            if docstring_body_lines:
                new_inner_content += "\n\n" + "\n".join(docstring_body_lines).strip()

            new_docstring = f'{quotes}{new_inner_content.strip()}{quotes}'

            shebang_lines = '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n'
            source_without_shebangs_and_docstring = source_code
            if has_shebang:
                source_without_shebangs_and_docstring = '\n'.join(lines[1:])
            if has_encoding:
                source_without_shebangs_and_docstring = '\n'.join(lines[2:])

            if raw_docstring is not None:
                new_source_code = source_without_shebangs_and_docstring.replace(raw_docstring, new_docstring, 1)
            else:
                new_source_code = source_without_shebangs_and_docstring

            new_source_code = shebang_lines + new_source_code

    else:
        if not issues:
            issues.append("No docstring found")

        if mode in ["fix-all", "fix", "interactive"]:
            new_header = get_header_template(relative_path_str, authors=authors)

            new_source_code = new_header + "\n" + source_code

            if has_shebang and has_encoding:
                old_lines = source_code.splitlines(True)
                new_source_code = new_header + "".join(old_lines[2:])

    if new_source_code and new_source_code != source_code:
        if mode == "interactive":
            confirm = input(f"  Apply changes to {relative_path_str}? (y/n): ").lower()
            if confirm != 'y':
                return {'file': relative_path_str, 'issues': issues, 'fixed': False, 'skipped': True}

        _write_file(file_path, new_source_code)
        return {'file': relative_path_str, 'issues': issues, 'fixed': True}

    if issues:
        return {'file': relative_path_str, 'issues': issues, 'fixed': False}

    return None


def main():
    """Main function to parse arguments and run the script."""
    parser = argparse.ArgumentParser(
        description="Check and fix file headers in Python source files."
    )

    parser.add_argument(
        "files", nargs='*', help="Files to process (usually passed by pre-commit)."
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--check", action="store_true", help="Dry run: check files but do not make changes."
    )
    mode_group.add_argument(
        "--fix-all", action="store_true", help="Automatically fix all incorrect headers."
    )
    mode_group.add_argument(
        "--interactive", action="store_true", help="Interactively review and apply fixes."
    )

    parser.add_argument(
        "--path", type=str, help="Specify a file or directory to process instead of scanning all includes."
    )
    parser.add_argument(
        "--authors", type=str, default=AUTHORS, help="Specify the author name(s) for new headers."
    )
    args = parser.parse_args()

    if args.files:
        if args.check:
            mode = "check"
        elif args.interactive:
            mode = "interactive"
        else:
            mode = "fix-all"
    elif args.check:
        mode = "check"
    elif args.fix_all:
        mode = "fix-all"
    elif args.interactive:
        mode = "interactive"
    elif args.path:
        mode = "fix"
    else:
        mode = "check"


    authors_to_use = args.authors

    files_to_process: List[Path] = []
    if args.files:
        files_to_process = [Path(f) for f in args.files]
    elif args.path:
        target_path = Path(args.path)
        if not target_path.is_absolute():
            target_path = PROJECT_ROOT / target_path

        if target_path.is_file() and target_path.suffix == ".py":
            files_to_process = [target_path]
        elif target_path.is_dir():
            files_to_process = list(find_python_files(target_path))
        else:
            print(f"Error: Path '{args.path}' is not a valid Python file or directory.", file=sys.stderr)
            sys.exit(1)
    else:
        files_to_process = list(find_python_files())


    issues_found_in_files: List[Dict[str, Any]] = []
    modified_files_count = 0

    for file_path in files_to_process:
        result = process_file(file_path, mode, authors_to_use)
        if result:
            issues_found_in_files.append(result)
            if result.get('fixed'):
                modified_files_count += 1

    if issues_found_in_files:
        print("\n--- Header Issues Found ---", file=sys.stderr)
        for issue_info in issues_found_in_files:
            file_name = issue_info['file']
            issues_list = issue_info['issues']
            fixed_status = issue_info.get('fixed', False)
            skipped_status = issue_info.get('skipped', False)

            if fixed_status:
                print(f"✅ Fixed: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)
            elif skipped_status:
                print(f"⚠️ Skipped: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)
            else:
                print(f"❌ Needs Fix: {file_name} (Issues: {', '.join(issues_list)})", file=sys.stderr)

        if mode == "check":
            print("\nTo fix these headers, run: make fix-all-headers --fix-all", file=sys.stderr)
            print("Or add to your pre-commit config with '--fix-all' argument.", file=sys.stderr)
        elif mode == "interactive":
            print("\nSome files were skipped or not fixed in interactive mode.", file=sys.stderr)
            print("To fix all remaining headers, run: make interactive-fix-headers --fix-all", file=sys.stderr)
        elif modified_files_count > 0:
            print(f"\nSuccessfully fixed {modified_files_count} file(s). Please re-stage and commit.", file=sys.stderr)

        sys.exit(1)
    else:
        print("All Python file headers are correct. ✨", file=sys.stdout)
        sys.exit(0)

if __name__ == "__main__":
    main()
