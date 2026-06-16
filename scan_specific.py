from detect_secrets import SecretsCollection
import json

secrets = SecretsCollection()
secrets.scan_file('mcpgateway/config.py')
secrets.scan_file('scripts/test_mcp_client.py')
secrets.scan_file('tests/integration/test_concurrency_row_locking.py')

print(json.dumps(secrets.json(), indent=2))
