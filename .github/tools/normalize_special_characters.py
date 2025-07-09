#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""normalize_characters: cleanup AI generated artifacts from code.

Copyright 2025 Mihai Criveti
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A **single-file** command-line utility that normalises so-called *"smart"* punctuation,
exotic Unicode glyphs, zero-width characters, and AI-generated artefacts to plain
ASCII. The intended use-case is cleaning up code blocks from ChatGPT, pasting
from the web, or tidying a repository before committing.

## Key features

- **No third-party dependencies** - standard library only.
- **One portable file** that you can vendor in any project.
- **Globs, directories or explicit files** are accepted as positional
  arguments, just like *black* or *ruff*.
- **Dry-run, diff, backup and warnings** switches help you adopt it safely.
- **Built-in configuration** - mappings, removals, warnings and ignore globs
  are all Python literals in this file, making the tool self-documenting.
- **Comprehensive ignore patterns** for modern development environments.
- **File type whitelist** - only processes specified file types.

Usage examples::

    # See which files would change and view a coloured unified diff
    python normalize_characters.py "**/*.py" --dry-run --diff

    # Clean the entire project tree, keeping *.bak* backups of changed files
    python normalize_characters.py . --backup-ext .bak

    # Normalise Markdown docs verbosely; ignore the vendor directory
    python normalize_characters.py "docs/**/*.md" -v -i "vendor/**/*"

    # Process only Python files in src/ directory
    python normalize_characters.py "src/**/*.py" --verbose

Exit codes:

    * **0** - success, no changes were necessary.
    * **1** - at least one file was modified (or would be, in *--dry-run*).

The script is intentionally opinionated but easy to fork - simply adjust
``DEFAULT_MAPPING``, ``DEFAULT_REGEX_REMOVE``, etc. to taste.
"""

# Future
from __future__ import annotations

# Standard
import argparse
import difflib
import fnmatch
import logging
from pathlib import Path
import re
import sys
from typing import Dict, Iterable, List, Optional, Pattern, Sequence

__all__ = [
    "main",
    "apply_char_map",
    "apply_removals",
    "gather_warnings",
    "find_files",
]

__version__ = "2.0.0"
_LOG = logging.getLogger("normalize_characters")

# ---------------------------------------------------------------------------
# Configurable rules – tweak these to suit your project
# ---------------------------------------------------------------------------

# Whitelist of allowed file extensions (only these files will be processed)
DEFAULT_ALLOWED_EXTENSIONS: List[str] = [
    # Programming languages
    ".py",          # Python
    ".js",          # JavaScript
    ".ts",          # TypeScript
    ".jsx",         # React JSX
    ".tsx",         # React TypeScript
    ".html",        # HTML
    ".htm",         # HTML
    ".css",         # CSS
    ".scss",        # Sass
    ".sass",        # Sass
    ".less",        # Less CSS
    ".php",         # PHP
    ".rb",          # Ruby
    ".go",          # Go
    ".rs",          # Rust
    ".java",        # Java
    ".c",           # C
    ".cpp",         # C++
    ".cxx",         # C++
    ".cc",          # C++
    ".h",           # C/C++ Header
    ".hpp",         # C++ Header
    ".hxx",         # C++ Header
    ".cs",          # C#
    ".swift",       # Swift
    ".kt",          # Kotlin
    ".scala",       # Scala
    ".clj",         # Clojure
    ".hs",          # Haskell
    ".ml",          # OCaml
    ".fs",          # F#
    ".dart",        # Dart
    ".lua",         # Lua
    ".r",           # R
    ".m",           # Objective-C/MATLAB
    ".pl",          # Perl
    ".pm",          # Perl Module

    # Shell and scripts
    ".sh",          # Shell script
    ".bash",        # Bash script
    ".zsh",         # Zsh script
    ".fish",        # Fish script
    ".ps1",         # PowerShell
    ".bat",         # Batch file
    ".cmd",         # Command file

    # Data and config files
    ".json",        # JSON
    ".yaml",        # YAML
    ".yml",         # YAML
    ".xml",         # XML
    ".toml",        # TOML
    ".ini",         # INI file
    ".cfg",         # Config file
    ".conf",        # Config file
    ".properties",  # Properties file
    ".env",         # Environment file

    # Documentation and text
    ".md",          # Markdown
    ".rst",         # reStructuredText
    ".txt",         # Plain text
    ".rtf",         # Rich text
    ".tex",         # LaTeX
    ".org",         # Org-mode

    # Database
    ".sql",         # SQL
    ".sqlite",      # SQLite
    ".psql",        # PostgreSQL

    # Web and markup
    ".svg",         # SVG (text-based)
    ".vue",         # Vue.js
    ".svelte",      # Svelte

    # Build and project files
    ".dockerfile",  # Dockerfile
    ".makefile",    # Makefile
    ".gradle",      # Gradle
    ".maven",       # Maven
    ".cmake",       # CMake
    ".gyp",         # GYP
    ".gypi",        # GYP

    # Version control
    ".gitignore",   # Git ignore
    ".gitattributes", # Git attributes

    # Without extension (common script files)
    "Dockerfile",
    "Makefile",
    "Rakefile",
    "Gemfile",
    "Pipfile",
    "requirements.txt",
    "setup.py",
    "pyproject.toml",
    "package.json",
    "tsconfig.json",
    "webpack.config.js",
    "rollup.config.js",
    "vite.config.js",
    "next.config.js",
    "nuxt.config.js",
    "tailwind.config.js",
    "postcss.config.js",
    "babel.config.js",
    "eslint.config.js",
    ".eslintrc",
    ".prettierrc",
    ".babelrc",
    ".editorconfig",
]

# fmt: off  # (Keep one-item-per-line style for readability.)
DEFAULT_MAPPING: Dict[str, str] = {
    # "Smart" double quotes & guillemets → plain double quote
    "“": '"',   # U+201C LEFT DOUBLE QUOTATION MARK
    "”": '"',   # U+201D RIGHT DOUBLE QUOTATION MARK
    "„": '"',   # U+201E DOUBLE LOW-9 QUOTATION MARK
    "‟": '"',   # U+201F DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    "«": '"',   # U+00AB LEFT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet)
    "»": '"',   # U+00BB RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK (guillemet)

    # "Smart" single quotes & apos-like glyphs → plain apostrophe
    "'": "'",   # U+2018 LEFT SINGLE QUOTATION MARK
    "'": "'",   # U+2019 RIGHT SINGLE QUOTATION MARK
    "’": "'",   # APOSTROPHE SINGLE QUOTATION MARK
    "‚": "'",   # U+201A SINGLE LOW-9 QUOTATION MARK
    "‛": "'",   # U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
    "ʼ": "'",   # U+02BC MODIFIER LETTER APOSTROPHE

    # Dashes (em, en, figure, minus, etc.) → ASCII hyphen-minus
    "—": "-",   # U+2014 EM DASH
    "–": "-",   # U+2013 EN DASH
    "‒": "-",   # U+2012 FIGURE DASH
    "‑": "-",   # U+2011 NON-BREAKING HYPHEN
    "‐": "-",   # U+2010 HYPHEN
    "⁃": "-",   # U+2043 HYPHEN BULLET
    "−": "-",   # U+2212 MINUS SIGN
    "﹣": "-",  # U+FE63 SMALL HYPHEN-MINUS
    "－": "-",  # U+FF0D FULLWIDTH HYPHEN-MINUS

    # Ellipsis → three dots
    "…": "...",  # U+2026 HORIZONTAL ELLIPSIS

    # Bullet & middle dot variants → hyphen for list markup
    "•": "-",   # U+2022 BULLET
    "·": "-",   # U+00B7 MIDDLE DOT
    "⁌": "-",   # U+204C BLACK LEFTWARDS BULLET
    "⁍": "-",   # U+204D BLACK RIGHTWARDS BULLET

    # Common copyright / trade marks
    "©": "(c)",   # U+00A9 COPYRIGHT SIGN
    "®": "(r)",   # U+00AE REGISTERED SIGN
    "™": "(tm)",  # U+2122 TRADE MARK SIGN

    # Vulgar fractions – cheap ASCII approximations
    "¼": "1/4",   # U+00BC VULGAR FRACTION ONE QUARTER
    "½": "1/2",   # U+00BD VULGAR FRACTION ONE HALF
    "¾": "3/4",   # U+00BE VULGAR FRACTION THREE QUARTERS

    # Non-breaking & other exotic spaces → regular space
    "\u00A0": " ",  # NO-BREAK SPACE
    "\u202F": " ",  # NARROW NO-BREAK SPACE
    "\u205F": " ",  # MEDIUM MATHEMATICAL SPACE
    "\u3000": " ",  # IDEOGRAPHIC SPACE (full-width)
    "\u2000": " ",  # EN QUAD
    "\u2001": " ",  # EM QUAD
    "\u2002": " ",  # EN SPACE
    "\u2003": " ",  # EM SPACE
    "\u2004": " ",  # THREE-PER-EM SPACE
    "\u2005": " ",  # FOUR-PER-EM SPACE
    "\u2006": " ",  # SIX-PER-EM SPACE
    "\u2007": " ",  # FIGURE SPACE
    "\u2008": " ",  # PUNCTUATION SPACE
    "\u2009": " ",  # THIN SPACE
    "\u200A": " ",  # HAIR SPACE

    # Zero-width & byte-order-mark characters – *delete entirely*
    "\u200B": "",   # ZERO WIDTH SPACE
    "\u200C": "",   # ZERO WIDTH NON-JOINER
    "\u200D": "",   # ZERO WIDTH JOINER
    "\u2060": "",   # WORD JOINER
    "\uFEFF": "",   # ZERO WIDTH NO-BREAK SPACE (BOM)
}
# fmt: on

# Patterns to strip out completely (e.g. ChatGPT citation artefacts)
DEFAULT_REGEX_REMOVE: List[str] = [
    r"::contentReference\[oaicite:\d+]\{index=\d+}",
]

# Warn-only patterns – flagged but not auto-fixed
DEFAULT_WARN_PATTERNS: List[str] = [
    r"\t",      # Literal TAB characters
    r"\r\n",    # Windows CRLF line endings
    r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]",  # Control characters
]

# Files & directories to ignore by default (glob syntax)
DEFAULT_IGNORES: List[str] = [
    # Self-reference - prevent the script from modifying itself
    "normalize_characters.py",
    "normalize_special_characters.py",
    "normalize-characters.py",
    "character_normalizer.py",
    "**/normalize_characters.py",
    "**/normalize_special_characters.py",
    "**/normalize-characters.py",
    "**/character_normalizer.py",

    # Version control
    ".git",
    ".git*",
    ".git/**",
    "**/.git/**/*",
    "**/.gitignore",
    "**/.gitmodules",
    "**/.gitattributes",
    "**/.hg/**/*",
    "**/.svn/**/*",

    # CI/CD and configuration
    "**/.github/**/*",
    "**/.gitlab-ci.yml",
    "**/.travis.yml",
    "**/.circleci/**/*",
    "**/.pre-commit-config.yaml",
    "**/pre-commit-config.yaml",

    # Python
    "**/__pycache__/**/*",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    "**/.venv/**/*",
    "**/venv/**/*",
    "**/env/**/*",
    "**/.tox/**/*",
    "**/.coverage",
    "**/.pytest_cache/**/*",
    "**/htmlcov/**/*",
    "**/.mypy_cache/**/*",
    "**/dist/**/*",
    "**/build/**/*",
    "**/*.egg-info/**/*",

    # Node.js
    "**/node_modules/**/*",
    "**/npm-debug.log*",
    "**/yarn-debug.log*",
    "**/yarn-error.log*",
    "**/.npm/**/*",
    "**/.yarn/**/*",
    "**/package-lock.json",
    "**/yarn.lock",

    # IDEs and editors
    "**/.vscode/**/*",
    "**/.idea/**/*",
    "**/*.swp",
    "**/*.swo",
    "**/*~",
    "**/.DS_Store",
    "**/Thumbs.db",

    # Compiled files and binaries
    "**/*.o",
    "**/*.so",
    "**/*.dll",
    "**/*.exe",
    "**/*.class",
    "**/*.jar",

    # Documentation builds
    "**/docs/_build/**/*",
    "**/site/**/*",

    # Temporary files
    "**/tmp/**/*",
    "**/temp/**/*",
    "**/*.tmp",
    "**/*.temp",
    "**/*.log",

    # Archives
    "**/*.zip",
    "**/*.tar.gz",
    "**/*.tar.bz2",
    "**/*.rar",
    "**/*.7z",

    # Images and media (usually binary)
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
    "**/*.ico",
    "**/*.mp4",
    "**/*.avi",
    "**/*.mov",
    "**/*.mp3",
    "**/*.wav",

    # Fonts
    "**/*.ttf",
    "**/*.otf",
    "**/*.woff",
    "**/*.woff2",
    "**/*.eot",

    # Database
    "mcp.db",
    "*.db",
    "**/*.db",
]

# ---------------------------------------------------------------------------
# Internal pre-compiled regexes – do not edit below unless you know why.
# ---------------------------------------------------------------------------

_CHAR_PATTERN = re.compile(
    "|".join(sorted(map(re.escape, DEFAULT_MAPPING), key=len, reverse=True))
)
_REMOVE_REGEX = [re.compile(p) for p in DEFAULT_REGEX_REMOVE]
_WARN_REGEX = [re.compile(p, re.MULTILINE) for p in DEFAULT_WARN_PATTERNS]

# ---------------------------------------------------------------------------
# Public helper functions (importable by unit tests)
# ---------------------------------------------------------------------------

def apply_char_map(text: str, mapping: Optional[Dict[str, str]] = None) -> str:
    """Replace all keys in mapping found in text with their values.

    Args:
        text: The input string to normalise.
        mapping: A custom mapping to use instead of DEFAULT_MAPPING.
                If None, uses the default mapping.

    Returns:
        The transformed string with characters replaced according to the mapping.

    Examples:
        >>> apply_char_map('"smart quotes"')
        '"smart quotes"'
        >>> apply_char_map('em—dash and en–dash')
        'em-dash and en-dash'
        >>> apply_char_map('custom', {'c': 'k', 'u': 'o'})
        'kostom'
        >>> apply_char_map('')
        ''
    """
    if not text:
        return text

    char_mapping = mapping if mapping is not None else DEFAULT_MAPPING
    if not char_mapping:
        return text

    rx = _CHAR_PATTERN if mapping is None else re.compile(
        "|".join(sorted(map(re.escape, char_mapping), key=len, reverse=True))
    )
    return rx.sub(lambda m: char_mapping[m.group(0)], text)


def apply_removals(text: str, patterns: Optional[Iterable[Pattern[str]]] = None) -> str:
    """Strip substrings that match patterns.

    Args:
        text: The input string to process.
        patterns: Regex patterns to remove. If None, uses _REMOVE_REGEX.

    Returns:
        String with matching patterns removed.

    Examples:
        >>> apply_removals('text::contentReference[oaicite:1]{index=0}more')
        'textmore'
        >>> apply_removals('hello world', [re.compile(r'world')])
        'hello '
        >>> apply_removals('')
        ''
        >>> apply_removals('no matches')
        'no matches'
    """
    if not text:
        return text

    regex_patterns = patterns if patterns is not None else _REMOVE_REGEX
    result = text
    for rx in regex_patterns:
        result = rx.sub("", result)
    return result


def gather_warnings(
    text: str,
    src: Path,
    warn_rx: Optional[Iterable[Pattern[str]]] = None
) -> List[str]:
    """Return a list of warning strings for each regex that matches text.

    Args:
        text: The text content to check for warnings.
        src: Path to the source file (for warning messages).
        warn_rx: Warning regex patterns. If None, uses _WARN_REGEX.

    Returns:
        List of warning messages for patterns that matched.

    Examples:
        >>> from pathlib import Path
        >>> import re
        >>> warnings = gather_warnings('text\\t', Path('test.txt'))
        >>> len(warnings) > 0  # Should warn about tab character
        True
        >>> gather_warnings('clean text', Path('test.txt'))
        []
        >>> patterns = [re.compile(r'bad', re.MULTILINE)]
        >>> gather_warnings('bad text', Path('file.py'), patterns)
        ["⚠ Warn: 'bad' matched in file.py"]
    """
    if not text:
        return []

    warning_patterns = warn_rx if warn_rx is not None else _WARN_REGEX
    return [
        f"⚠ Warn: {rx.pattern!r} matched in {src}"
        for rx in warning_patterns
        if rx.search(text)
    ]


def is_allowed_file(path: Path, allowed_extensions: Optional[Sequence[str]] = None) -> bool:
    """Check if a file is in the allowed extensions whitelist.

    Args:
        path: Path to the file to check.
        allowed_extensions: List of allowed extensions. If None, uses DEFAULT_ALLOWED_EXTENSIONS.

    Returns:
        True if the file should be processed, False otherwise.

    Examples:
        >>> is_allowed_file(Path('test.py'))
        True
        >>> is_allowed_file(Path('test.exe'))
        False
        >>> is_allowed_file(Path('Dockerfile'))
        True
        >>> is_allowed_file(Path('test.custom'), ['.custom'])
        True
    """
    extensions = allowed_extensions if allowed_extensions is not None else DEFAULT_ALLOWED_EXTENSIONS

    # Check exact filename matches (for files like Dockerfile, Makefile, etc.)
    if path.name in extensions:
        return True

    # Check file extension
    if path.suffix.lower() in [ext.lower() for ext in extensions]:
        return True

    return False


def find_files(inputs: Sequence[str], ignore: Sequence[str], allowed_extensions: Optional[Sequence[str]] = None) -> List[Path]:
    """Expand inputs (files/directories/globs) into a unique list of Path objects.

    Args:
        inputs: List of file paths, directory paths, or glob patterns.
        ignore: List of glob patterns to ignore.
        allowed_extensions: List of allowed file extensions. If None, uses DEFAULT_ALLOWED_EXTENSIONS.

    Returns:
        Sorted list of unique Path objects that match inputs but not ignore patterns
        and are in the allowed extensions whitelist.

    Examples:
        >>> import tempfile
        >>> import os
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     # Create test files
        ...     test_py = Path(tmpdir) / 'test.py'
        ...     test_py.write_text('print("hello")')
        ...     test_exe = Path(tmpdir) / 'test.exe'
        ...     test_exe.write_text('binary')
        ...     # Test finding files
        ...     files = find_files([tmpdir], [])
        ...     len([f for f in files if f.name == 'test.py']) == 1
        14
        True
        >>> find_files([], [])
        []
    """
    if not inputs:
        return []

    paths: List[Path] = []
    for token in inputs:
        p = Path(token)
        if p.is_file():
            paths.append(p)
            continue
        if p.is_dir():
            token = str(p / "**/*")
        try:
            for match in Path().glob(token):
                if match.is_file():
                    rel = match.as_posix()
                    if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                        continue
                    # Check if file is in whitelist
                    if not is_allowed_file(match, allowed_extensions):
                        continue
                    paths.append(match)
        except OSError:
            # Handle invalid glob patterns gracefully
            continue
    return sorted(set(paths))


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _diff(before: str, after: str, filename: str) -> str:
    """Return unified diff between before and after as a single string.

    Args:
        before: Original text content.
        after: Modified text content.
        filename: Name of the file for diff headers.

    Returns:
        Unified diff string, empty if no differences.

    Examples:
        >>> diff_output = _diff('old line', 'new line', 'test.txt')
        >>> 'test.txt:before' in diff_output
        True
        >>> 'test.txt:after' in diff_output
        True
        >>> _diff('same', 'same', 'test.txt')
        ''
    """
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{filename}:before",
            tofile=f"{filename}:after",
        )
    )


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Define and parse all CLI arguments.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Returns:
        Parsed argument namespace.

    Examples:
        >>> args = _parse_args(['file.py'])
        >>> args.inputs
        ['file.py']
        >>> args = _parse_args(['--dry-run', 'file.py'])
        >>> args.dry_run
        True
        >>> args.verbose  # Should be True due to dry-run implying verbose
        True
    """
    p = argparse.ArgumentParser(
        prog="normalize-characters",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Normalize smart quotes, exotic whitespace, and AI artefacts to plain ASCII.",
    )
    p.add_argument(
        "inputs",
        nargs="+",
        help="Files, directories or globs (e.g. '**/*.md').",
    )
    p.add_argument(
        "-i",
        "--ignore",
        action="append",
        default=[],
        help="Additional ignore patterns (glob syntax).",
    )
    p.add_argument(
        "--no-default-ignore",
        action="store_true",
        help="Disable built-in ignore rules.",
    )
    p.add_argument(
        "--allowed-extensions",
        action="append",
        default=[],
        help="Additional allowed file extensions (e.g., '.custom').",
    )
    p.add_argument(
        "--no-default-extensions",
        action="store_true",
        help="Disable built-in allowed extensions whitelist.",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not write files (disabled by default).")
    p.add_argument("--diff", action="store_true", help="Show unified diff.")
    p.add_argument(
        "--backup-ext",
        default="",
        help="Save backup to <file><ext> before overwrite.",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress output (except warnings)."
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Show processed files.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    ns = p.parse_args(argv)
    if ns.diff or ns.dry_run:
        ns.verbose = True  # Imply verbose when printing diff or dry-run
    if ns.quiet:
        ns.verbose = False
    return ns


# ---------------------------------------------------------------------------
# Main program logic
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:  # noqa: C901
    """Entry-point function for normalize-characters CLI.

    Processes files according to command line arguments, normalizing characters
    and generating appropriate output/warnings.

    Args:
        argv: Command line arguments. If None, uses sys.argv.

    Examples:
        >>> import sys
        >>> from io import StringIO
        >>> from unittest.mock import patch
        >>> # Test main with dry-run (would need real files for full test)
        >>> # This is a simplified example showing the function signature
        >>> main is not None
        True
    """
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose and not args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    ignore = [] if args.no_default_ignore else list(DEFAULT_IGNORES)
    ignore.extend(args.ignore)

    allowed_extensions = [] if args.no_default_extensions else list(DEFAULT_ALLOWED_EXTENSIONS)
    allowed_extensions.extend(args.allowed_extensions)

    files = find_files(args.inputs, ignore, allowed_extensions)
    if not files:
        _LOG.warning("No files matched.")
        sys.exit(0)

    changed = warned = 0
    for path in files:
        try:
            original = path.read_text(encoding="utf-8", errors="surrogateescape")
        except Exception as exc:
            _LOG.warning("Could not read %s: %s", path, exc)
            continue

        fixed = apply_char_map(original)
        fixed = apply_removals(fixed)
        warnings = gather_warnings(fixed, path)
        warned += len(warnings)

        for w in warnings:
            _LOG.warning(w)

        if original == fixed:
            if args.verbose:
                _LOG.info("✓ %s (no change)", path)
            continue

        changed += 1
        if args.verbose:
            _LOG.info("✏ %s", path)

        if args.diff:
            sys.stdout.write(_diff(original, fixed, str(path)))

        if not args.dry_run:
            try:
                if args.backup_ext:
                    backup = path.with_suffix(path.suffix + args.backup_ext)
                    backup.write_text(original, encoding="utf-8", errors="surrogateescape")
                path.write_text(fixed, encoding="utf-8", errors="surrogateescape")
            except Exception as exc:
                _LOG.warning("Could not write %s: %s", path, exc)

    if not args.quiet:
        _LOG.info(
            "Processed %d file(s): %d changed, %d warnings%s.",
            len(files),
            changed,
            warned,
            " (dry-run)" if args.dry_run else "",
        )

    sys.exit(1 if changed else 0)


# ---------------------------------------------------------------------------
# Stand-alone execution guard
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
