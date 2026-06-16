"""Fix .secrets.baseline to match what CI's detect-secrets scan produces.

CI removes entries for files where secrets have been suppressed via
'# pragma: allowlist secret' inline comments. When the scanner no longer
finds the secret (because the pragma suppresses it), it removes the entry
from the baseline. If we commit a baseline with stale entries, the CI
pre-commit hook regenerates the baseline, detects a diff, and fails.

This script removes exactly the entries CI removes:
- mcpgateway/config.py (all entries - suppressed via pragma)
- scripts/test_mcp_client.py (all entries - suppressed via pragma)
"""
import json

with open('.secrets.baseline', 'r', encoding='utf-8') as f:
    content = f.read()

data = json.loads(content)

# Files whose entries CI removes (secrets now suppressed via pragma)
files_to_remove = [
    'mcpgateway/config.py',
    'scripts/test_mcp_client.py',
]

for filepath in files_to_remove:
    if filepath in data['results']:
        del data['results'][filepath]
        print(f"Removed: {filepath}")
    else:
        print(f"Already absent: {filepath}")

# Write back with same formatting (2-space indent, sorted keys, LF line endings)
output = json.dumps(data, indent=2, sort_keys=True)

with open('.secrets.baseline', 'w', encoding='utf-8', newline='\n') as f:
    f.write(output)
    f.write('\n')  # Trailing newline

print("Done. Baseline updated.")
