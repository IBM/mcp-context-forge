# Design: Configure ContextForge Plugins on IBM Cloud Code Engine

## Goal

Create a how-to guide that walks users through managing ContextForge plugin
configuration via a Code Engine ConfigMap, using the `PLUGINS_CONFIG_FILE`
environment variable to point the gateway at a mounted configuration file.

## Audience

Operators who already have a running ContextForge deployment on IBM Cloud Code
Engine (per the existing IBM Cloud how-to) and want to enable and configure
plugins without rebuilding the container image.

## Approach

Standalone how-to document in `docs/docs/howto/`. References the IBM Cloud
deployment guide as a prerequisite. Uses two example plugins:

- **PIIFilterPlugin** — PII detection and masking (covers both "PII" and
  "Masking" use cases since masking is a feature within this plugin)
- **UnifiedPDPPlugin** — Unified Policy Decision Point for access control

## Mechanism

1. Create a minimal `plugins.yaml` file locally with global settings and the
   two plugins in `enforce` mode
2. Upload it as a Code Engine ConfigMap:
   `ibmcloud ce configmap create --name cf-plugins --from-file config.yaml=plugins.yaml`
3. Update the app to mount the ConfigMap and set env vars:
   `ibmcloud ce app update --mount-configmap /app/config=cf-plugins --env PLUGINS_ENABLED=true --env PLUGINS_CONFIG_FILE=/app/config/config.yaml`
4. Verify plugins loaded via health/admin endpoints
5. Show how to update the ConfigMap and roll the app to pick up changes

## Document Structure (~250 lines)

1. Prerequisites (running CE deployment, CLI)
2. Create the plugin config file (full YAML shown)
3. Upload as ConfigMap
4. Mount and enable plugins on the app
5. Verify plugins are active
6. Customize plugin settings (brief examples)
7. Update the ConfigMap
8. Troubleshooting table

## Style

- Admonitions for warnings/tips
- No tabbed content (all CLI-based — Code Engine has no Admin UI for ConfigMaps)
- Cross-references to plugin configuration reference and IBM Cloud deployment how-to

## Decision Record

- No standalone "Masking" plugin exists; masking is covered via PIIFilterPlugin's
  `default_mask_strategy` and `redaction_text` settings
- `PLUGINS_CONFIG_FILE` default is `plugins/config.yaml`; we override to
  `/app/config/config.yaml` to match the ConfigMap mount path
- The Helm chart uses the same pattern (ConfigMap → volume mount → env var),
  validating this approach
