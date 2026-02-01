# Module documentation

## ✍️ File Header Management

To ensure consistency, all Python source files must include a standardized header containing metadata like copyright, license, and authors. We use a script to automate the checking and fixing of these headers.

**By default, the script runs in check mode (dry run) and will NOT modify any files unless explicitly told to do so with fix flags.**

### 🔍 Checking Headers (No Modifications)

These commands only check files and report issues without making any changes:

*   **`make check-headers`**:
    Scans all Python files in `mcpgateway/` and `tests/` and reports any files with missing or incorrect headers. This is the default behavior.

    ```bash
    make check-headers
    ```

*   **`make check-headers-diff`**:
    Same as `check-headers` but also shows a diff preview of what would be changed.

    ```bash
    make check-headers-diff
    ```

*   **`make check-headers-debug`**:
    Checks headers with additional debug information (file permissions, shebang status, etc.).

    ```bash
    make check-headers-debug
    ```

*   **`make check-header`**:
    Check a specific file or directory without modifying it.

    ```bash
    # Check a single file
    make check-header path="mcpgateway/main.py"

    # Check with debug info and diff preview
    make check-header path="tests/" debug=1 diff=1
    ```

### 🔧 Fixing Headers (Will Modify Files)

**⚠️ WARNING**: These commands WILL modify your files. Always commit your changes before running fix commands.

*   **`make fix-all-headers`**:
    Automatically fixes all Python files with incorrect headers across the entire project.

    ```bash
    make fix-all-headers
    ```

*   **`make fix-all-headers-no-encoding`**:
    Fix all headers but don't require the encoding line (`# -*- coding: utf-8 -*-`).

    ```bash
    make fix-all-headers-no-encoding
    ```

*   **`make fix-all-headers-custom`**:
    Fix all headers with custom configuration options.

    ```bash
    # Custom copyright year
    make fix-all-headers-custom year=2024

    # Custom license
    make fix-all-headers-custom license=MIT

    # Custom shebang requirement
    make fix-all-headers-custom shebang=always

    # Combine multiple options
    make fix-all-headers-custom year=2024 license=MIT shebang=never
    ```

*   **`make interactive-fix-headers`**:
    Scans all files and prompts for confirmation before applying each fix. This gives you full control over which files are modified.

    ```bash
    make interactive-fix-headers
    ```

*   **`make fix-header`**:
    Fix headers for a specific file or directory with various options.

    ```bash
    # Fix a single file
    make fix-header path="mcpgateway/main.py"

    # Fix all files in a directory
    make fix-header path="tests/unit/"

    # Fix with specific authors
    make fix-header path="mcpgateway/models.py" authors="John Doe, Jane Smith"

    # Fix with custom shebang requirement
    make fix-header path="scripts/" shebang=always

    # Fix without encoding line
    make fix-header path="lib/helper.py" encoding=no

    # Combine multiple options
    make fix-header path="mcpgateway/" authors="Team Alpha" shebang=auto encoding=no
    ```

### 📋 Header Format

The standardized header format is:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Module Description.
Location: ./relative/path/to/file.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Author Name(s)

Your module documentation continues here...
"""
```

### ⚙️ Configuration Options

*   **`authors`**: Specify author name(s) for the header
*   **`shebang`**: Control shebang requirement

    - `auto` (default): Only required for executable files
    - `always`: Always require shebang line
    - `never`: Never require shebang line

*   **`encoding`**: Set to `no` to skip encoding line requirement
*   **`year`**: Override copyright year (for `fix-all-headers-custom`)
*   **`license`**: Override license identifier (for `fix-all-headers-custom`)
*   **`debug`**: Set to `1` to show debug information (for check commands)
*   **`diff`**: Set to `1` to show diff preview (for check commands)

### 🪝 Pre-commit Integration

For use with pre-commit hooks:

```bash
# Check only (recommended for pre-commit)
make pre-commit-check-headers

# Fix mode (use with caution)
make pre-commit-fix-headers
```

### 💡 Best Practices

1. **Always run `check-headers` first** to see what needs to be fixed
2. **Commit your code before running fix commands** to allow easy rollback
3. **Use `interactive-fix-headers`** when you want to review each change
4. **Use `check-headers-diff`** to preview changes before applying them
5. **Executable scripts** should have shebang lines - the script detects this automatically in `auto` mode

---
