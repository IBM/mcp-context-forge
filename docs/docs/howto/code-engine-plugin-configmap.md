# Configure ContextForge Plugins on Code Engine

Manage your ContextForge plugin configuration externally using an IBM Cloud Code Engine ConfigMap. This approach lets you enable, disable, and tune plugins without rebuilding the container image or modifying the deployment script.

!!! abstract "Prerequisites"

    - A running ContextForge deployment on IBM Cloud Code Engine — see [Deploy ContextForge on IBM Cloud with Code Engine](ibm-cloud-code-engine.md)
    - IBM Cloud CLI with the Code Engine plugin (`ibmcloud plugin install code-engine`)
    - Your Code Engine project selected (`ibmcloud ce project select --name <project>`)

---

## 1 - Create the Plugin Configuration File

Create a file called `plugins.yaml` on your local machine. The example below enables two plugins:

- **PIIFilterPlugin** — detects and masks personally identifiable information in tool inputs and outputs
- **UnifiedPDPPlugin** — enforces access-control policies before tool invocation

```yaml
# plugins.yaml — ContextForge plugin configuration for Code Engine

plugin_dirs:
  - "plugins/native"
  - "plugins/custom"

plugin_settings:
  parallel_execution_within_band: true
  plugin_timeout: 120
  fail_on_plugin_error: false
  enable_plugin_api: true
  plugin_health_check_interval: 120

plugins:
  # PII Filter — detect and mask sensitive data
  - name: "PIIFilterPlugin"
    kind: "cpex_pii_filter.PIIFilterPlugin"
    description: "Detects and masks Personally Identifiable Information"
    version: "0.1.0"
    hooks:
      - "prompt_pre_fetch"
      - "prompt_post_fetch"
      - "tool_pre_invoke"
      - "tool_post_invoke"
    tags: ["security", "pii", "compliance"]
    mode: "enforce"
    priority: 50
    conditions: []
    config:
      detect_ssn: true
      detect_credit_card: true
      detect_email: true
      detect_phone: true
      detect_ip_address: false
      detect_aws_keys: true
      detect_api_keys: true
      default_mask_strategy: "partial"   # redact | partial | hash | tokenize | remove
      redaction_text: "[PII_REDACTED]"
      block_on_detection: false
      log_detections: true
      include_detection_details: true
      whitelist_patterns: []

  # Unified Policy Decision Point — access-control enforcement
  - name: "UnifiedPDPPlugin"
    kind: "plugins.unified_pdp.unified_pdp.UnifiedPDPPlugin"
    description: "Unified Policy Decision Point for access control"
    version: "0.1.0"
    hooks:
      - "tool_pre_invoke"
      - "resource_pre_fetch"
    tags: ["security", "policy", "access-control"]
    mode: "enforce"
    priority: 10
    conditions: []
    config:
      engines:
        - name: native
          enabled: true
          priority: 1
          settings:
            rules_file: "plugins/unified_pdp/default_rules.json"
      combination_mode: "all_must_allow"
      default_decision: "deny"
      cache:
        enabled: true
        ttl_seconds: 60
        max_entries: 10000
      performance:
        timeout_ms: 1000
        parallel_evaluation: true
```

!!! tip "More plugins"

    The example above shows two plugins. ContextForge ships with 30+ plugins
    covering argument normalization, content filtering, caching, webhooks, and
    more. See the [Plugin Configuration Reference](../manage/configuration-plugins.md)
    and the full default config at `plugins/config.yaml` in the source repository.

---

## 2 - Upload the ConfigMap

Create a Code Engine ConfigMap from the local file. The `--from-file` flag maps
the ConfigMap key `config.yaml` to the contents of your local `plugins.yaml`:

```bash
ibmcloud ce configmap create \
  --name cf-plugins \
  --from-file config.yaml=plugins.yaml
```

!!! note "ConfigMap key becomes filename"

    The key name before the `=` sign (`config.yaml`) is the filename that will
    appear inside the container when the ConfigMap is mounted. The value after
    `=` is the local file to read.

Verify the ConfigMap was created:

```bash
ibmcloud ce configmap get --name cf-plugins
```

---

## 3 - Mount and Enable Plugins

Update the application to mount the ConfigMap into the container and set the
required environment variables:

```bash
ibmcloud ce application update \
  --name mcpgateway \
  --mount-configmap /app/config=cf-plugins \
  --env PLUGINS_ENABLED=true \
  --env PLUGINS_CONFIG_FILE=/app/config/config.yaml
```

This command:

1. Mounts the `cf-plugins` ConfigMap at `/app/config/` inside the container
2. Sets `PLUGINS_ENABLED=true` to activate the plugin framework
3. Sets `PLUGINS_CONFIG_FILE` to the mounted config file path

!!! warning "Triggers a new revision"

    The `application update` command creates a new application revision and
    rolls it out. Existing requests drain to the previous revision while the
    new one starts.

---

## 4 - Verify Plugins Are Active

### Confirm the application is running

```bash
ibmcloud ce application get --name mcpgateway | grep -E "Status|URL|Ready"
```

### Check the health endpoint

```bash
APP_URL=$(ibmcloud ce application get --name mcpgateway --output url)
curl -s "$APP_URL/health" | jq .
```

Expected output includes `"status": "healthy"`.

### Confirm plugins loaded

If you have the Admin API enabled (`MCPGATEWAY_ADMIN_API_ENABLED=true`), query
the plugins endpoint:

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  "$APP_URL/admin/plugins" | jq .
```

You should see both `PIIFilterPlugin` and `UnifiedPDPPlugin` listed with
`"mode": "enforce"`.

!!! tip "Check application logs"

    If plugins are not loading as expected, inspect the application logs:

    ```bash
    ibmcloud ce application logs --name mcpgateway --follow
    ```

    Look for lines containing `plugin` or `PIIFilter` to confirm initialization.

---

## 5 - Update the ConfigMap

To change plugin settings — for example, to switch PII masking from `partial` to
`redact` — edit your local `plugins.yaml`, then update the ConfigMap and
trigger a new revision:

```bash
# Update the ConfigMap contents
ibmcloud ce configmap update \
  --name cf-plugins \
  --from-file config.yaml=plugins.yaml

# Trigger a new revision to pick up the changes
ibmcloud ce application update --name mcpgateway
```

!!! note "ConfigMap changes require a new revision"

    Code Engine does not automatically propagate ConfigMap changes to running
    instances. You must update the application (even with no other changes) to
    create a new revision that picks up the updated ConfigMap.

---

## 6 - Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Plugins not loading | `PLUGINS_ENABLED` not set to `true` | `ibmcloud ce application update --name mcpgateway --env PLUGINS_ENABLED=true` |
| Config parse error in logs | Invalid YAML syntax | Validate with `python3 -c "import yaml; yaml.safe_load(open('plugins.yaml'))"` before uploading |
| "Config file not found" error | `PLUGINS_CONFIG_FILE` path does not match the mount path | Verify mount path and env var match — both should use `/app/config/config.yaml` |
| App crashes on startup | Plugin `kind` path does not match an installed plugin class | Check the `kind` field matches the module path in the container image |
| PII not being detected | Plugin mode set to `disabled` or `permissive` | Set `mode: "enforce"` in the PIIFilterPlugin config |
| Policy engine denying all requests | `default_decision: "deny"` with no rules loaded | Add rules to `plugins/unified_pdp/default_rules.json` or change `default_decision` to `"allow"` for testing |
| Changes not taking effect | ConfigMap updated but no new revision | Run `ibmcloud ce application update --name mcpgateway` to trigger a rollout |

---

## Related Documentation

- [Plugin Configuration Reference](../manage/configuration-plugins.md) — All plugin framework settings and environment variables
- [Plugin User Guide](../using/plugins/index.md) — Plugin concepts, hooks, and architecture
- [Deploy ContextForge on IBM Cloud with Code Engine](ibm-cloud-code-engine.md) — Initial Code Engine deployment setup
