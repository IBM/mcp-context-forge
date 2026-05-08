#!/usr/bin/env python3
"""Update Python test file paths to use /v1/ prefix after Phase 1 migration.

ONE-TIME USE: Run once during the API_v1 migration (PR #4403). Re-running is safe
(idempotent — already-prefixed paths are skipped), but this script has no further
purpose after the migration is complete.

Routes now under /v1/ (inside v1_router):
  tools, servers (CRUD), gateways, prompts, resources, protocol,
  roots, tags, a2a, export, import, teams, tokens, rbac, llm,
  admin, auth, observability, toolops, cancellation, metrics (entity metrics)

Routes that stay unversioned (do NOT add /v1):
  /.well-known/..., /servers/{id}/.well-known/..., /oauth/...,
  /version, /health, /ready, /health/security, /_internal/...,
  /api/logs/..., /api/metrics/..., /mcp
"""

import re
import sys
from pathlib import Path

# Root of the repo
ROOT = Path(__file__).parent.parent

# Simple path segments that always go under /v1/ (no exceptions)
SIMPLE_RESOURCES = [
    "tools",
    "gateways",
    "prompts",
    "resources",
    "protocol",
    "roots",
    "tags",
    "a2a",
    "export",
    "import",
    "teams",
    "tokens",
    "rbac",
    "llm",
    "toolops",
    "observability",
    "cancellation",
]


def needs_v1_prefix(line: str, resource: str) -> bool:
    """Return True if the path in line needs a /v1/ prefix added."""
    # Already has /v1/ - skip
    if f'"/v1/{resource}' in line or f"'/v1/{resource}" in line:
        return False
    return True


def replace_simple_resource(content: str, resource: str) -> str:
    """Replace "/<resource> and '/<resource> with "/v1/<resource> and '/v1/<resource>."""
    # Only replace when NOT already prefixed with /v1/ or /api/
    # Pattern: quote + / + resource (not preceded by v1/ or api/)
    content = re.sub(
        rf'"/(?!v1/|api/)({resource}[/"\'?])',
        r'"/v1/\1',
        content,
    )
    content = re.sub(
        rf"'/(?!v1/|api/)({resource}[/'\"?])",
        r"'/v1/\1",
        content,
    )
    # Handle exact resource path ending (no trailing slash/quote)
    content = re.sub(
        rf'"/(?!v1/|api/)({resource})"',
        r'"/v1/\1"',
        content,
    )
    content = re.sub(
        rf"'/(?!v1/|api/)({resource})'",
        r"'/v1/\1'",
        content,
    )
    return content


def replace_servers(content: str) -> str:
    """Replace /servers/ paths but NOT /servers/{id}/.well-known/ paths."""
    # First, protect .well-known paths with a sentinel
    sentinel = "__WELLKNOWN_SERVERS__"
    content = re.sub(
        r'"/servers/([^"]*\.well-known[^"]*)"',
        lambda m: f'"__WKS__{m.group(1)}__WKS__"',
        content,
    )
    content = re.sub(
        r"'/servers/([^']*\.well-known[^']*)'",
        lambda m: f"'__WKS__{m.group(1)}__WKS__'",
        content,
    )

    # Now do the broad /servers replacement
    content = re.sub(
        r'"/(?!v1/|api/)servers([/"\'?])',
        r'"/v1/servers\1',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)servers([/'\"?])",
        r"'/v1/servers\1",
        content,
    )
    content = re.sub(
        r'"/(?!v1/|api/)servers"',
        r'"/v1/servers"',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)servers'",
        r"'/v1/servers'",
        content,
    )

    # Restore the protected .well-known paths (undo the /v1/ that might have been added)
    content = re.sub(
        r'"/v1/servers/__WKS__([^"]*?)__WKS__"',
        lambda m: f'"/servers/{m.group(1)}"',
        content,
    )
    content = re.sub(
        r"'/v1/servers/__WKS__([^']*?)__WKS__'",
        lambda m: f"'/servers/{m.group(1)}'",
        content,
    )
    # Also handle non-replaced sentinel (if no /v1/ was added)
    content = re.sub(
        r'"/servers/__WKS__([^"]*?)__WKS__"',
        lambda m: f'"/servers/{m.group(1)}"',
        content,
    )
    content = re.sub(
        r"'/servers/__WKS__([^']*?)__WKS__'",
        lambda m: f"'/servers/{m.group(1)}'",
        content,
    )
    return content


def replace_admin(content: str) -> str:
    """Replace /admin/ paths (but not /api/admin/)."""
    content = re.sub(
        r'"/(?!v1/|api/)admin([/"\'?])',
        r'"/v1/admin\1',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)admin([/'\"?])",
        r"'/v1/admin\1",
        content,
    )
    content = re.sub(
        r'"/(?!v1/|api/)admin"',
        r'"/v1/admin"',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)admin'",
        r"'/v1/admin'",
        content,
    )
    return content


def replace_metrics(content: str) -> str:
    """Replace /metrics/ paths but not /api/metrics/ paths."""
    content = re.sub(
        r'"/(?!v1/|api/)metrics([/"\'?])',
        r'"/v1/metrics\1',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)metrics([/'\"?])",
        r"'/v1/metrics\1",
        content,
    )
    content = re.sub(
        r'"/(?!v1/|api/)metrics"',
        r'"/v1/metrics"',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)metrics'",
        r"'/v1/metrics'",
        content,
    )
    return content


def replace_auth(content: str) -> str:
    """Replace /auth/ paths."""
    content = re.sub(
        r'"/(?!v1/|api/)auth([/"\'?])',
        r'"/v1/auth\1',
        content,
    )
    content = re.sub(
        r"'/(?!v1/|api/)auth([/'\"?])",
        r"'/v1/auth\1",
        content,
    )
    return content


def fix_double_v1(content: str) -> str:
    """Fix any accidentally double-prefixed paths."""
    content = content.replace('"/v1/v1/', '"/v1/')
    content = content.replace("'/v1/v1/", "'/v1/")
    return content


def process_file(filepath: Path) -> bool:
    """Process a single file, returning True if changed."""
    try:
        original = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"ERROR reading {filepath}: {e}", file=sys.stderr)
        return False

    content = original

    # Apply simple resource replacements
    for resource in SIMPLE_RESOURCES:
        content = replace_simple_resource(content, resource)

    # Apply special cases
    content = replace_servers(content)
    content = replace_admin(content)
    content = replace_metrics(content)
    content = replace_auth(content)

    # Fix any double /v1/v1/ that might have occurred
    content = fix_double_v1(content)

    if content != original:
        filepath.write_text(content, encoding="utf-8")
        return True
    return False


def find_python_test_files(root: Path):
    """Find all Python test files under tests/."""
    tests_dir = root / "tests"
    return list(tests_dir.rglob("*.py"))


def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    files = find_python_test_files(ROOT)
    changed = []
    errors = []

    for f in sorted(files):
        try:
            was_changed = process_file(f)
            if was_changed:
                changed.append(f)
                if verbose:
                    print(f"  CHANGED: {f.relative_to(ROOT)}")
        except Exception as e:
            errors.append((f, e))
            print(f"  ERROR: {f.relative_to(ROOT)}: {e}", file=sys.stderr)

    print(f"\nSummary: {len(changed)} files changed, {len(errors)} errors out of {len(files)} total")
    if changed and not verbose:
        for f in changed:
            print(f"  {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
