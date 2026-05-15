"""Fix hardcoded /admin/login redirects to /v1/admin/login in source files.

ONE-TIME USE: Run once during the API_v1 migration (PR #4403). Re-running on an
already-migrated codebase will silently no-op (regex guards against double-prefixing),
but this script has no further purpose after the migration is complete.
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

files = [
    ROOT / "mcpgateway/middleware/rbac.py",
    ROOT / "mcpgateway/utils/verify_credentials.py",
    ROOT / "mcpgateway/routers/sso.py",
    ROOT / "mcpgateway/admin.py",
    ROOT / "mcpgateway/main.py",
]

# Match /admin/ followed by login, logout, forgot-password, reset-password
# but NOT if already preceded by /v1
PATTERN = re.compile(r'(?<!/v1)(/admin/(?:login|logout|forgot-password|reset-password))')

for filepath in files:
    content = filepath.read_text()
    fixed = PATTERN.sub(r"/v1\1", content)
    if fixed != content:
        filepath.write_text(fixed)
        print(f"Fixed: {filepath.relative_to(ROOT)}")
    else:
        print(f"No changes: {filepath.relative_to(ROOT)}")
