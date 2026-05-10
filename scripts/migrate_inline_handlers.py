#!/usr/bin/env python3
"""
Migrate inline event handlers to data-action attributes for CSP compliance.

This script converts inline event handlers (onclick, oninput, etc.) to
data-action-* attributes that work with the event delegation system.

Usage:
    python scripts/migrate_inline_handlers.py [--dry-run] [--file FILE]
"""

import re
import sys
import argparse
from pathlib import Path
from typing import List, Tuple

# Event handler patterns to migrate
EVENT_HANDLERS = [
    'onclick',
    'oninput',
    'onchange',
    'onsubmit',
    'onkeydown',
    'onfocus',
    'onblur',
    'onload',
]

def parse_handler_call(handler_value: str) -> Tuple[str, List[str]]:
    """
    Parse a handler call to extract function name and arguments.

    Examples:
        "Admin.showTab('tools')" -> ("showTab", ["'tools'"])
        "Admin.openGlobalSearchModal()" -> ("openGlobalSearchModal", [])
        "Admin.filterServerTable(this.value)" -> ("filterServerTable", ["this.value"])
    """
    # Remove Admin. prefix if present
    handler_value = handler_value.strip()
    if handler_value.startswith('Admin.'):
        handler_value = handler_value[6:]

    # Extract function name and arguments
    match = re.match(r'(\w+)\((.*?)\)$', handler_value, re.DOTALL)
    if not match:
        return handler_value, []

    func_name = match.group(1)
    args_str = match.group(2).strip()

    if not args_str:
        return func_name, []

    # Parse arguments (simple approach - handles most cases)
    args = []
    current_arg = ''
    paren_depth = 0
    in_string = False
    string_char = None

    for char in args_str:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            current_arg += char
        elif char == string_char and in_string:
            in_string = False
            string_char = None
            current_arg += char
        elif char == '(' and not in_string:
            paren_depth += 1
            current_arg += char
        elif char == ')' and not in_string:
            paren_depth -= 1
            current_arg += char
        elif char == ',' and paren_depth == 0 and not in_string:
            args.append(current_arg.strip())
            current_arg = ''
        else:
            current_arg += char

    if current_arg.strip():
        args.append(current_arg.strip())

    return func_name, args


def convert_handler_to_data_action(event_type: str, handler_value: str) -> str:
    """
    Convert an inline handler to data-action format.

    Args:
        event_type: The event type (e.g., 'click', 'input')
        handler_value: The handler code (e.g., "Admin.showTab('tools')")

    Returns:
        String with data-action attributes
    """
    # Remove 'return' statement if present
    handler_value = handler_value.strip()
    if handler_value.startswith('return '):
        handler_value = handler_value[7:].strip()

    func_name, args = parse_handler_call(handler_value)

    # Build data-action attribute
    result = f'data-action-{event_type}="{func_name}"'

    # Add arguments as data-arg0, data-arg1, etc.
    arg_index = 0
    for arg in args:
        # Handle special cases
        if arg == 'this.value':
            # For input/change events, the value is automatically passed
            continue
        elif arg == 'this.checked':
            # For checkbox change events, checked state is automatically passed
            continue
        elif arg == 'event' or arg == 'e':
            # Event is automatically passed
            continue
        elif arg == 'this' or arg.startswith('this.'):
            # For 'this' references, we need to use a special marker
            # The event delegation system will handle this
            arg_escaped = arg.replace('"', '"')
            result += f' data-arg{arg_index}="{arg_escaped}"'
            arg_index += 1
        elif arg.startswith('() =>') or arg.startswith('function'):
            # Skip inline functions - these need manual review
            continue
        else:
            # Escape quotes in the argument value
            arg_escaped = arg.replace('"', '"')
            result += f' data-arg{arg_index}="{arg_escaped}"'
            arg_index += 1

    return result


def migrate_file(file_path: Path, dry_run: bool = False) -> Tuple[int, List[str]]:
    """
    Migrate inline handlers in a single file.

    Returns:
        Tuple of (number of replacements, list of changes)
    """
    content = file_path.read_text(encoding='utf-8')
    original_content = content
    changes = []
    replacement_count = 0

    for event_handler in EVENT_HANDLERS:
        event_type = event_handler[2:]  # Remove 'on' prefix

        # Pattern to match inline event handlers
        # Matches: onclick="Admin.function(args)" or onclick='Admin.function(args)'
        pattern = rf'{event_handler}=(["\'])(.*?)\1'

        def replace_handler(match):
            nonlocal replacement_count, changes
            quote = match.group(1)
            handler_value = match.group(2)

            # Skip if already converted
            if 'data-action-' in handler_value:
                return match.group(0)

            # Convert to data-action format
            data_action = convert_handler_to_data_action(event_type, handler_value)

            replacement_count += 1
            changes.append(f"  {event_handler}={quote}{handler_value}{quote}")
            changes.append(f"  -> {data_action}")

            return data_action

        content = re.sub(pattern, replace_handler, content, flags=re.DOTALL)

    if not dry_run and content != original_content:
        file_path.write_text(content, encoding='utf-8')

    return replacement_count, changes


def main():
    parser = argparse.ArgumentParser(
        description='Migrate inline event handlers to data-action attributes'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='Migrate a specific file instead of all templates'
    )

    args = parser.parse_args()

    # Determine which files to process
    if args.file:
        files = [Path(args.file)]
    else:
        # Process all template files
        template_dir = Path('mcpgateway/templates')
        files = list(template_dir.glob('*.html'))

    if not files:
        print("No files found to process")
        return 1

    total_replacements = 0
    files_modified = 0

    for file_path in sorted(files):
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue

        print(f"\nProcessing: {file_path}")
        replacements, changes = migrate_file(file_path, dry_run=args.dry_run)

        if replacements > 0:
            files_modified += 1
            total_replacements += replacements
            print(f"  {replacements} handlers migrated")

            if args.dry_run and changes:
                print("  Changes:")
                for change in changes[:10]:  # Show first 10 changes
                    print(f"    {change}")
                if len(changes) > 10:
                    print(f"    ... and {len(changes) - 10} more")
        else:
            print("  No handlers found")

    print(f"\n{'DRY RUN - ' if args.dry_run else ''}Summary:")
    print(f"  Files processed: {len(files)}")
    print(f"  Files modified: {files_modified}")
    print(f"  Total handlers migrated: {total_replacements}")

    if args.dry_run:
        print("\nRun without --dry-run to apply changes")

    return 0


if __name__ == '__main__':
    sys.exit(main())
