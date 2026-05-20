# API Connect FAM Plugin - Troubleshooting

## Plugin Works But No Logs Visible

The plugin is working correctly (as verified by the test), but you may not see logs when running `make dev` due to log level settings.

### Solution 1: Set LOG_LEVEL in .env

Edit your `.env` file and add/uncomment:

```bash
LOG_LEVEL=INFO
```

Then restart the server:

```bash
make dev
```

### Solution 2: Set LOG_LEVEL as Environment Variable

```bash
LOG_LEVEL=INFO make dev
```

### Solution 3: Check if Logs are Going to a File

If `LOG_TO_FILE=true` in your `.env`, logs might be written to a file instead of console:

```bash
tail -f mcpgateway.log
```

### Solution 4: Use Structured Logging

If using JSON logging, logs might be harder to read. Set:

```bash
LOG_FORMAT=text
```

## Verify Plugin is Loaded

Run this command to test the plugin directly:

```bash
source /Users/shankarn/.venv/mcpgateway/bin/activate
python -c "
import asyncio
import sys
import logging
sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from plugins.apiconnect_fam.apiconnect_fam import APIConnectFAMPlugin
from mcpgateway.plugins.framework import PluginConfig

async def test():
    config = PluginConfig(
        name='APIConnectFAM',
        kind='plugins.apiconnect_fam.apiconnect_fam.APIConnectFAMPlugin',
        hooks=[],
        priority=1000,
        config={'interval_seconds': 5, 'log_details': True}
    )
    plugin = APIConnectFAMPlugin(config)
    await plugin.initialize()
    await asyncio.sleep(10)
    await plugin.shutdown()

asyncio.run(test())
"
```

You should see output like:

```
INFO - Initializing APIConnectFAMPlugin with interval=5s
INFO - Virtual Servers Summary: Total=1, Enabled=1, Disabled=0
INFO - [ENABLED] test (ID: e48f91c5e9964e31a0bca96a50880e79)
```

## Check Plugin Configuration

Verify the plugin is in the config:

```bash
python -c "
import yaml
with open('plugins/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
    plugins = config.get('plugins', [])
    apiconnect_fam = [p for p in plugins if p.get('name') == 'APIConnectFAM']
    if apiconnect_fam:
        print('APIConnectFAM found in config')
        print(f\"Mode: {apiconnect_fam[0].get('mode')}\")
    else:
        print('APIConnectFAM NOT found in config')
"
```

## Common Issues

### 1. Plugin Not Loading

**Check:**
- `PLUGINS_ENABLED=true` in `.env`
- `PLUGINS_CONFIG_FILE=plugins/config.yaml` in `.env`
- Plugin mode is not `disabled` in `plugins/config.yaml`

### 2. No Server Data

If you see "No virtual servers found in the system", create a test server:

```bash
export TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com \
  --exp 0 \
  --secret my-test-key-but-now-longer-than-32-bytes)

curl -X POST http://localhost:8000/servers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Server",
    "description": "Test virtual server",
    "enabled": true
  }'
```

### 3. Logs Too Frequent

Increase the interval in `plugins/config.yaml`:

```yaml
config:
  interval_seconds: 300  # Log every 5 minutes
```

### 4. Too Much Detail

Disable detailed logging:

```yaml
config:
  log_details: false  # Only show summary
```

## Quick Test with Shorter Interval

For testing, you can temporarily set a shorter interval (5 seconds) in `plugins/config.yaml`:

```yaml
config:
  interval_seconds: 5  # Log every 5 seconds (for testing)
  log_details: true
```

Then run:

```bash
LOG_LEVEL=INFO make dev
```

You should see logs every 5 seconds.

## Expected Log Output

With `log_details: true`:

```
INFO - Initializing APIConnectFAMPlugin with interval=60s
INFO - Virtual Servers Summary: Total=1, Enabled=1, Disabled=0
INFO - ================================================================================
INFO -   [ENABLED] test (ID: e48f91c5e9964e31a0bca96a50880e79)
INFO -     Description: sample
INFO -     Created: 2026-04-21 09:05:30.250227
INFO -     Items: 3 tools, 0 resources, 0 prompts
INFO - --------------------------------------------------------------------------------
INFO - ================================================================================
```

With `log_details: false`:

```
INFO - Initializing APIConnectFAMPlugin with interval=60s
INFO - Virtual Servers Summary: Total=1, Enabled=1, Disabled=0