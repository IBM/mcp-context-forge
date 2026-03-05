# Plugin ConfigMap How-To Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a how-to guide for configuring ContextForge plugins via IBM Cloud Code Engine ConfigMap.

**Architecture:** Single new Markdown file in `docs/docs/howto/`, plus navigation updates to `.pages` and `index.md`.

**Tech Stack:** MkDocs Material, pymdownx admonitions, IBM Cloud CLI (`ibmcloud ce`)

---

### Task 1: Create the how-to document

**Files:**
- Create: `docs/docs/howto/code-engine-plugin-configmap.md`

**Step 1: Write the complete how-to document**

The document should contain these sections in order:

1. **Title and intro** — "Configure ContextForge Plugins on Code Engine"
   - One-paragraph description: manage plugin config externally via ConfigMap
   - Prerequisites box: running CE deployment (link to ibm-cloud-code-engine.md), `ibmcloud` CLI with `ce` plugin, `PLUGINS_ENABLED=true`

2. **Section 1: Create the Plugin Configuration File** — Show a complete `plugins.yaml` with:
   - `plugin_dirs` (standard paths)
   - `plugin_settings` (parallel execution, timeout, fail_on_plugin_error: false)
   - Two plugins:
     - PIIFilterPlugin in `enforce` mode, priority 50, hooks: prompt_pre_fetch/prompt_post_fetch/tool_pre_invoke/tool_post_invoke, with config for detect_ssn/credit_card/email/aws_keys/api_keys=true, default_mask_strategy=partial, redaction_text=[PII_REDACTED], block_on_detection=false, log_detections=true
     - UnifiedPDPPlugin in `enforce` mode, priority 10, hooks: tool_pre_invoke/resource_pre_fetch, with native engine enabled (rules_file path adjusted to /app/config/default_rules.json or noting it needs a separate ConfigMap/embedded), combination_mode=all_must_allow, default_decision=deny, cache enabled

   Tip admonition: link to plugin configuration reference for all available plugins and settings.

3. **Section 2: Upload the ConfigMap** — CLI command:
   ```
   ibmcloud ce configmap create \
     --name cf-plugins \
     --from-file config.yaml=plugins.yaml
   ```
   Note admonition: ConfigMap key (`config.yaml`) becomes the filename inside the mount.

4. **Section 3: Mount and Enable Plugins** — CLI command:
   ```
   ibmcloud ce app update \
     --name context-forge \
     --mount-configmap /app/config=cf-plugins \
     --env PLUGINS_ENABLED=true \
     --env PLUGINS_CONFIG_FILE=/app/config/config.yaml
   ```
   Warning admonition: This triggers a new revision/rollout.

5. **Section 4: Verify Plugins Are Active** — Three verification methods:
   - `ibmcloud ce app get --name context-forge` to confirm RUNNING
   - `curl` the health endpoint
   - `curl` the `/admin/plugins` or `/api/v1/plugins` endpoint to see loaded plugins (with example JSON output)

6. **Section 5: Update the ConfigMap** — Show update + restart:
   ```
   ibmcloud ce configmap update --name cf-plugins --from-file config.yaml=plugins.yaml
   ibmcloud ce app update --name context-forge
   ```
   Note: Code Engine doesn't auto-reload ConfigMap changes; a new revision is needed.

7. **Section 6: Troubleshooting** — Table with columns Symptom | Cause | Fix:
   - Plugins not loading → PLUGINS_ENABLED not true → set env var
   - Config parse error → YAML syntax issue → validate with `yamllint`
   - Mount path mismatch → PLUGINS_CONFIG_FILE doesn't match mount → verify paths
   - App crashes on start → plugin kind path wrong → check kind field matches installed plugin
   - PII not detected → mode set to disabled → change to enforce
   - Policy denying everything → default_decision=deny with no rules → add rules or switch to allow

8. **Related Documentation** — Links to:
   - Plugin Configuration Reference (configuration-plugins.md)
   - Deploy on IBM Cloud with Code Engine (ibm-cloud-code-engine.md)
   - Plugin User Guide (using/plugins/index.md)

**Step 2: Verify the file renders correctly**

Run: Visual inspection of Markdown structure, admonition syntax, code blocks.

**Step 3: Commit**

```bash
git add docs/docs/howto/code-engine-plugin-configmap.md
git commit -s -m "docs: add how-to for configuring plugins via Code Engine ConfigMap"
```

---

### Task 2: Update navigation files

**Files:**
- Modify: `docs/docs/howto/.pages`
- Modify: `docs/docs/howto/index.md`

**Step 1: Add new page to .pages nav**

Add `code-engine-plugin-configmap.md` after `ibm-cloud-code-engine.md` in the nav list.

**Step 2: Add link to index.md**

Add a new bullet in the "Available Guides" section linking to the new document.

**Step 3: Commit**

```bash
git add docs/docs/howto/.pages docs/docs/howto/index.md
git commit -s -m "docs: add plugin ConfigMap how-to to navigation"
```
