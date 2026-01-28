Plugins: How They Work in MCP Context Forge

- Purpose: Concise, code-grounded guidance for LLMs to reason about, write, and configure plugins in this gateway.
- Scope: In‑process (native) Python plugins and external plugins over MCP (STDIO or Streamable HTTP), unified by a single interface and common hook lifecycle.

**Big Picture**
- Hybrid model: Runs both self-contained plugins in‑process and external plugins as MCP servers; both implement the same hook interface.
- Lifecycle hooks: Six production hooks cover prompts, tools, and resources: `prompt_pre_fetch`, `prompt_post_fetch`, `tool_pre_invoke`, `tool_post_invoke`, `resource_pre_fetch`, `resource_post_fetch`.
- Sequential execution: Plugins execute in priority order (ascending). Each result can modify payloads or block processing.
- Modes: `enforce`, `enforce_ignore_error`, `permissive`, `disabled` control blocking and error behavior.
- Context sharing: Per-request GlobalContext plus per-plugin PluginContext with shared state across pre/post pairs; gateway auto-cleans stale contexts.
- Configuration: Single YAML at `plugins/config.yaml` (Jinja-enabled). Strict Pydantic validation; per-plugin conditions for selective execution.
- Safety: Per-call timeouts, payload size guardrails, error isolation, and audit visibility.

**Core Interfaces**
- Base class: `mcpgateway.plugins.framework.base.Plugin`
  - Exposes async methods for each hook; plugins override only the hooks they need.
  - Properties from config: `.name`, `.mode`, `.priority`, `.hooks`, `.tags`, `.conditions`.
- Hook payload/result models (Pydantic) in `mcpgateway/plugins/framework/models.py`:
  - Prompt
    - `PromptPrehookPayload(name: str, args: dict[str, str])`
    - `PromptPosthookPayload(name: str, result: PromptResult)`
    - Results: `PromptPrehookResult`, `PromptPosthookResult`
  - Tool
    - `ToolPreInvokePayload(name: str, args: dict[str, Any])`
    - `ToolPostInvokePayload(name: str, result: Any)`
    - Results: `ToolPreInvokeResult`, `ToolPostInvokeResult`
  - Resource
    - `ResourcePreFetchPayload(uri: str, metadata: dict[str, Any])`
    - `ResourcePostFetchPayload(uri: str, content: Any)`
    - Results: `ResourcePreFetchResult`, `ResourcePostFetchResult`
  - Result schema for all hooks: `PluginResult[T]` with fields
    - `continue_processing: bool = True`
    - `modified_payload: Optional[T]` (when transforming)
    - `violation: Optional[PluginViolation]` (when blocking or auditing)
    - `metadata: dict[str, Any] = {}` (accumulates across plugins)
- Violation schema: `PluginViolation(reason, description, code, details)`; manager injects `violation.plugin_name` at runtime.
- Contexts in `models.py`
  - `GlobalContext(request_id, user?, tenant_id?, server_id?, state={}, metadata={})`
  - `PluginContext(state={}, global_context: GlobalContext, metadata={})` with helpers `get_state`/`set_state`.

**Hook Semantics**
- `prompt_pre_fetch`: Before retrieving/rendering a prompt. Typical: validate/transform args; mask PII; may block.
- `prompt_post_fetch`: After rendering. Typical: filter/sanitize content; add metadata.
- `tool_pre_invoke`: Before executing a tool. Typical: auth/validation; policy checks; arg mutation; may block.
- `tool_post_invoke`: After tool returns. Typical: redact outputs; transform result; audit metadata.
- `resource_pre_fetch`: Before fetching URI. Typical: protocol/domain checks; metadata injection; may block.
- `resource_post_fetch`: After content is fetched. Typical: size checks; redaction; content transformation.

**Execution Model**
- Ordering: Deterministic, by ascending `priority`. Lower runs first.
- Conditions: A plugin's `conditions` must match for the current context to execute it. Fields include `server_ids`, `tenant_ids`, `tools`, `prompts`, `resources`, `user_patterns`, `content_types`. Matching helpers in `utils.py`.
- Modes and blocking:
  - `enforce`: If a result sets `continue_processing=False`, manager immediately returns a block with the violation.
  - `enforce_ignore_error`: Enforce violations; errors don't block (manager may continue based on global settings).
  - `permissive`: Log/report violations; continue.
  - `disabled`: Loaded but not executed.
- Timeouts and errors:
  - Per-plugin timeout (default 30s) enforced via `asyncio.wait_for`.
  - Payload size guardrails (~1MB) for prompt args and results.
  - Error isolation: behavior controlled by `plugin_settings.fail_on_plugin_error` and plugin `mode`.
- Context lifecycle: Manager stores per-request plugin contexts between pre/post hooks and cleans them periodically (every 5m; expire at 1h).

**Configuration File (`plugins/config.yaml`)**
- Top-level keys: `plugins: []`, `plugin_dirs: []`, `plugin_settings: {}`.
- Plugin entries (validated by `PluginConfig`):
  - `name`: unique id
  - `kind`: fully-qualified class path for native, or literal `external` for MCP plugins
  - `description`, `version`, `author`, `tags`
  - `hooks`: any of the six production hooks
  - `mode`: `enforce | enforce_ignore_error | permissive | disabled`
  - `priority`: int (smaller → earlier)
  - `conditions`: list of selector blocks (see Execution Model)
  - `applied_to` (optional): advanced targeting templates for tools/prompts/resources and context extraction
  - `config`: plugin-specific dict (native only; external config lives on the external server)
  - `mcp` (external only):
    - `proto`: `STDIO | STREAMABLEHTTP | SSE`
    - `url` for HTTP-like transports, `script` for STDIO (.py required)
- Global `plugin_settings`:
  - `parallel_execution_within_band` (reserved)
  - `plugin_timeout` (seconds)
  - `fail_on_plugin_error` (bool)
  - `enable_plugin_api` (bool)
  - `plugin_health_check_interval` (reserved)
- Jinja support: File is rendered with Jinja; `${env}` values can be injected from environment.

**External Plugins over MCP**
- Client: `ExternalPlugin` in `external/mcp/client.py` handles session, tool calls, merging remote config into local.
- Required tool names on server match hook names:
  - `get_plugin_config`
  - `prompt_pre_fetch`, `prompt_post_fetch`
  - `tool_pre_invoke`, `tool_post_invoke`
  - `resource_pre_fetch`, `resource_post_fetch`
- Call contract (JSON over MCP):
  - Request to each hook: `{ "plugin_name": str, "payload": <HookPayload>, "context": <PluginContext> }`
  - Response expected as JSON text with one of:
    - `{ "result": <PluginResult serialized> }`
    - `{ "context": <PluginContext serialized> }` (to update context)
    - `{ "error": <PluginErrorModel> }` to signal errors
- `get_plugin_config` must return a `PluginConfig`-compatible JSON; the gateway merges remote+local with local taking precedence for gateway-owned fields. For external plugins, gateway-side `config` is disallowed (plugin's own server owns it).
- Transports: `STDIO` (spawn python script) or `STREAMABLEHTTP` (connect to `url`).
- Validation: `script` must exist and be `.py`; `url` must pass security validation.

**Authoring Workflow**
- CLI: `mcpplugins bootstrap --destination <dir> [--type native|external]` creates a project from templates in `plugin_templates/`.
  - Native template: Python class extending `Plugin`, with `plugin-manifest.yaml.jinja`, example config, and README.
  - External template: Full project with runtime config, tests, container build, and MCP server entrypoint.
- External plugin dev loop (from Lifecycle docs):
  1) `make install-dev` (or `make install-editable`)
  2) Configure `resources/plugins/config.yaml` and `resources/runtime/config.yaml`
  3) `make test`
  4) `make build` (containerized MCP server)
  5) `make start` (default Streamable HTTP at `http://localhost:8000/mcp`)
  6) Integrate with gateway by adding to gateway's `plugins/config.yaml`:
     ```yaml
     - name: "MyFilter"
       kind: "external"
       priority: 10
      mcp:
        proto: STREAMABLEHTTP
        url: http://localhost:8000/mcp
        # tls:
        #   ca_bundle: /app/certs/plugins/ca.crt
        #   client_cert: /app/certs/plugins/gateway-client.pem
     ```
  - STDIO alternative:
     ```yaml
     - name: "MyFilter"
       kind: "external"
       priority: 10
       mcp:
         proto: STDIO
         script: path/to/server.py
     ```
- Enable framework in gateway: `.env` must set `PLUGINS_ENABLED=true` and optionally `PLUGIN_CONFIG_FILE=plugins/config.yaml`. To reuse a gateway-wide mTLS client certificate for multiple external plugins, set `PLUGINS_MTLS_CA_BUNDLE`, `PLUGINS_MTLS_CLIENT_CERT`, and related `PLUGINS_MTLS_*` variables. Individual plugin `tls` blocks override these defaults.

**Built‑in Plugins (39 plugins in 42 directories)**

Security & Filtering:
- `pii_filter` - PII detection and masking (SSN, credit card, email, phone, IP, keys)
- `deny_filter` - Denylist word blocking
- `secrets_detection` - Secret/credential detection
- `content_moderation` - Content moderation
- `harmful_content_detector` - Harmful content detection
- `code_safety_linter` - Code safety validation

Validation:
- `schema_guard` - Schema validation
- `sql_sanitizer` - SQL injection prevention
- `safe_html_sanitizer` - HTML sanitization
- `file_type_allowlist` - File type restrictions
- `citation_validator` - Citation validation
- `robots_license_guard` - Robots.txt and license compliance
- `sparc_static_validator` - Static validation
- `resource_filter` - URI/protocol/domain validation, size limits

Data Processing:
- `argument_normalizer` - Unicode, whitespace, casing, date, number normalization
- `markdown_cleaner` - Markdown cleanup
- `html_to_markdown` - HTML to Markdown conversion
- `code_formatter` - Code formatting
- `json_repair` - JSON repair and normalization
- `altk_json_processor` - ALTK JSON processing
- `ai_artifacts_normalizer` - AI artifact normalization
- `timezone_translator` - Timezone conversion
- `summarizer` - Content summarization

Optimization:
- `cached_tool_result` - Tool result caching
- `response_cache_by_prompt` - Response caching
- `circuit_breaker` - Circuit breaker pattern
- `retry_with_backoff` - Retry logic with backoff
- `rate_limiter` - Rate limiting
- `output_length_guard` - Output length limits

Utilities:
- `header_injector` - HTTP header injection
- `license_header_injector` - License header injection
- `privacy_notice_injector` - Privacy notice injection
- `tools_telemetry_exporter` - Telemetry export
- `webhook_notification` - Webhook notifications

External Services:
- `virus_total_checker` - VirusTotal integration
- `url_reputation` - URL reputation checking
- `watchdog` - Monitoring/watchdog
- `vault` - HashiCorp Vault integration

Examples:
- `examples/` - Example plugin templates
- `external/` - External plugin examples (OPA policy enforcement)

**Key Plugin Examples:**
- `ArgumentNormalizer` (`plugins/argument_normalizer/argument_normalizer.py`)
  - Hooks: prompt pre, tool pre
  - Normalizes Unicode (NFC/NFD/NFKC/NFKD), trims/collapses whitespace, optional casing, numeric date strings to ISO `YYYY-MM-DD`, and numbers to canonical form (dot decimal, no thousands). Per-field overrides via regex.
  - Config: `enable_unicode`, `unicode_form`, `remove_control_chars`, `enable_whitespace`, `trim`, `collapse_internal`, `normalize_newlines`, `collapse_blank_lines`, `enable_casing`, `case_strategy`, `enable_dates`, `day_first`, `year_first`, `enable_numbers`, `decimal_detection`, `field_overrides`.
  - Ordering: place before PII filter (lower priority value) so PII patterns see stabilized inputs. Recommended mode: `permissive`.
- `PIIFilterPlugin` (`plugins/pii_filter/pii_filter.py`)
  - Hooks: prompt pre/post, tool pre/post
  - Detects and masks PII (SSN, credit card, email, phone, IP, keys, etc.) via regex; supports strategies: redact/partial/hash/tokenize/remove
  - Config: detection toggles, `default_mask_strategy`, `redaction_text`, `block_on_detection`, `log_detections`, `whitelist_patterns`, `custom_patterns`
  - Behavior: may block in `enforce`, otherwise modifies payload (masked values) and sets metadata
- `SearchReplacePlugin` (`plugins/regex_filter/search_replace.py`)
  - Hooks: prompt pre/post, tool pre/post
  - Regex search/replace on string fields; config: `words: [{search, replace}, ...]`
- `DenyListPlugin` (`plugins/deny_filter/deny.py`)
  - Hooks: prompt pre
  - Blocks when any denylisted word is found in prompt args; config: `words: []`
- `ResourceFilterPlugin` (`plugins/resource_filter/resource_filter.py`)
  - Hooks: resource pre/post
  - Validates protocol/URI, size limits, domain blocks, content redaction; adds request metadata; config includes `max_content_size`, `allowed_protocols`, `blocked_domains`, `content_filters`
- External OPA example (`plugins/external/opa`)
  - Demonstrates external policy enforcement at `tool_pre_invoke` by calling an OPA server; shows `applied_to` usage to target specific tools and feed policy context.

**Manager and Registry Behavior**
- `PluginManager` (singleton)
  - Loads config via `ConfigLoader` (Jinja + YAML); instantiates via `PluginLoader`.
  - Executes per-hook via `PluginExecutor`, validates payload size, enforces timeouts, manages contexts, aggregates metadata.
  - Stores per-request contexts between pre/post and cleans them periodically.
- `PluginInstanceRegistry`
  - Registers `PluginRef` (wrapping plugins with UUIDs), keeps per-hook lists, returns plugins ordered by priority.

**Practical Tips for LLM‑Written Plugins**
- Keep hook methods pure async and non-blocking; respect timeouts.
- Only set `violation` and `continue_processing=False` to block; otherwise return `continue_processing=True` with optional `modified_payload`.
- If you modify the payload, return a fully-formed payload object of the same type; the manager threads it to subsequent plugins.
- Use `context.state` for local plugin data; use `context.global_context.state` to share across plugins; do not mutate `global_context.metadata` directly—prefer adding to `context.metadata` and structured result metadata.
- External servers must return exactly one of `result`, `context`, or `error` per call; JSON is passed as string content in MCP responses.
- External plugin `get_plugin_config` should advertise hooks, priority, and metadata; the gateway will merge with gateway-side fields and re-validate.

**Example: Minimal Native Plugin**
```python
from mcpgateway.plugins.framework import Plugin, PluginConfig, PluginContext
from mcpgateway.plugins.framework import PromptPrehookPayload, PromptPrehookResult
from mcpgateway.plugins.framework import PluginViolation

class MyGuard(Plugin):
    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        if payload.args and any("forbidden" in v for v in payload.args.values() if isinstance(v, str)):
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Forbidden content",
                    description="Blocked by MyGuard",
                    code="FORBIDDEN",
                    details={"matched": True},
                ),
            )
        return PromptPrehookResult(modified_payload=payload)
```

**Example: Register Native Plugin**
```yaml
plugins:
  - name: "MyGuard"
    kind: "plugins.my_guard.plugin.MyGuard"
    hooks: ["prompt_pre_fetch"]
    mode: "enforce"
    priority: 100
```

**Example: External Plugin Tool (TypeScript outline)**
```ts
// Tool name must be one of the hook names, e.g., "tool_pre_invoke"
// The server must also implement "get_plugin_config"
@Tool("tool_pre_invoke")
async function toolPreInvoke({ payload, context }: any) {
  // Return { result: PluginResult } as MCP JSON text
  // e.g., allow and add metadata
  return {
    continue_processing: true,
    metadata: { checked: true }
  };
}
```

**Environment and Enablement**
- Enable plugins in gateway `.env`: `PLUGINS_ENABLED=true` and optionally `PLUGIN_CONFIG_FILE=plugins/config.yaml`.
- Run gateway: `make dev` (reload) or `make serve`.
- Validate config: `make check-env` and `make doctest test` for framework models.

**Security and Limits**
- Timeouts: Default 30s per hook; tune via `plugin_settings.plugin_timeout`.
- Size limits: ~1MB for prompt args and rendered results; large payloads raise `PayloadSizeError`.
- Error isolation: Set `fail_on_plugin_error` for strict behavior; otherwise errors in permissive plugins don't block.
- External validation: `script` must exist and end with `.py`; `url` is validated; avoid injecting secrets in YAML—use env vars and Jinja.

**Roadmap Hooks (Not Yet Implemented)**
- Server lifecycle: `server_pre_register`, `server_post_register`
- Authentication: `auth_pre_check`, `auth_post_check`
- Federation: `federation_pre_sync`, `federation_post_sync`

**Where to Look in the Code**
- Framework: `mcpgateway/plugins/framework/{base.py,models.py,manager.py,registry.py,loader/,external/mcp/client.py}`
- Built-in plugins: `plugins/{argument_normalizer,pii_filter,regex_filter,deny_filter,resource_filter}`
- Gateway config: `plugins/config.yaml`
- Templates and CLI: `plugin_templates/` and CLI `mcpplugins` in `mcpgateway/plugins/tools/cli.py`; prompts handled by `copier.yml`.

**Testing Plugins**
- Code quality & pre-commit (see AGENTS.md for details):
  - `make autoflake isort black pre-commit` formats, orders imports, applies autoflake, and runs pre-commit hooks.
  - `make pylint flake8` runs static analysis; fix findings before committing.
  - `make doctest test` executes doctests then pytest; mirrors CI expectations locally.

- Root-level commands:
  - `make test` runs unit tests.
  - `make doctest` runs doctests embedded in framework models and helpers.
  - `make htmlcov` generates HTML coverage at `docs/docs/coverage/index.html`.
  - Use `pytest -k "name"` and marks (e.g., `pytest -m "not slow"`).

- Unit test a native plugin (pytest):
  ```python
  import pytest
  from mcpgateway.plugins.framework import (
      HookType, PluginConfig, PluginContext, GlobalContext,
      PromptPrehookPayload, PromptPrehookResult,
  )
  from plugins.regex_filter.search_replace import SearchReplacePlugin

  @pytest.mark.asyncio
  async def test_regex_search_replace_prompt_pre():
      cfg = PluginConfig(
          name="sr",
          kind="plugins.regex_filter.search_replace.SearchReplacePlugin",
          hooks=[HookType.PROMPT_PRE_FETCH],
          priority=100,
          config={"words": [{"search": "crap", "replace": "crud"}]},
      )
      plugin = SearchReplacePlugin(cfg)
      payload = PromptPrehookPayload(name="greeting", args={"text": "crap happens"})
      ctx = PluginContext(global_context=GlobalContext(request_id="t-1"))

      res: PromptPrehookResult = await plugin.prompt_pre_fetch(payload, ctx)
      assert res.continue_processing
      assert res.modified_payload.args["text"] == "crud happens"
  ```

- Unit test violation behavior (native):
  ```python
  import pytest
  from mcpgateway.plugins.framework import (
      HookType, PluginConfig, PluginContext, GlobalContext,
      PromptPrehookPayload, PluginViolation,
  )
  from plugins.deny_filter.deny import DenyListPlugin

  @pytest.mark.asyncio
  async def test_denylist_blocks():
      cfg = PluginConfig(
          name="deny",
          kind="plugins.deny_filter.deny.DenyListPlugin",
          hooks=[HookType.PROMPT_PRE_FETCH],
          priority=10,
          config={"words": ["blocked"]},
      )
      plugin = DenyListPlugin(cfg)
      payload = PromptPrehookPayload(name="any", args={"x": "this is blocked text"})
      ctx = PluginContext(global_context=GlobalContext(request_id="t-2"))

      res = await plugin.prompt_pre_fetch(payload, ctx)
      assert res.continue_processing is False
      assert isinstance(res.violation, PluginViolation)
  ```

- Integration test the pipeline via `PluginManager`:
  ```python
  import pytest
  from mcpgateway.plugins.framework.manager import PluginManager
  from mcpgateway.plugins.framework import GlobalContext, PromptPrehookPayload

  @pytest.mark.asyncio
  async def test_manager_runs_plugins(tmp_path):
      # Create a minimal config.yaml scoped to test
      cfg = tmp_path / "plugins.yaml"
      cfg.write_text(
          """
          plugins:
            - name: "PIIFilterPlugin"
              kind: "plugins.pii_filter.pii_filter.PIIFilterPlugin"
              hooks: ["prompt_pre_fetch"]
              mode: "permissive"
              priority: 1
              config:
                detect_email: true
                default_mask_strategy: "partial"
          plugin_settings:
            plugin_timeout: 5
            fail_on_plugin_error: false
          plugin_dirs: []
          """,
          encoding="utf-8",
      )

      mgr = PluginManager(str(cfg), timeout=5)
      await mgr.initialize()
      ctx = GlobalContext(request_id="req-1")
      payload = PromptPrehookPayload(name="p", args={"msg": "email me at dev@example.com"})
      res, _ = await mgr.prompt_pre_fetch(payload, ctx)

      assert res.continue_processing
      assert res.modified_payload is None or "@example.com" in (res.modified_payload.args.get("msg", ""))
      await mgr.shutdown()
  ```

- Testing external plugins (unit):
  - For server code, unit test the underlying policy/transform functions directly, and mock I/O (e.g., mock `requests.post` in the OPA plugin).
  - Keep tests deterministic and fast; avoid network in unit tests.

- Testing external plugins (integration with MCP client):
  1) In the external plugin project directory, start the MCP server: `make start` (default Streamable HTTP at `http://localhost:8000/mcp`).
  2) From a test, connect using the MCP Python client and call the hook tool:
     ```python
     import pytest, json
     from mcp import ClientSession
     from mcp.client.streamable_http import streamablehttp_client
     from mcpgateway.plugins.framework.models import HookType

     @pytest.mark.asyncio
     async def test_mcp_server_tool_pre_invoke():
         async with (await streamablehttp_client("http://localhost:8000/mcp")) as (http, write, _):
             async with ClientSession(http, write) as session:
                 await session.initialize()
                 # Minimal payload/context as JSON-serializable dicts
                 payload = {"name": "some_tool", "args": {"x": "y"}}
                 context = {"state": {}, "metadata": {}, "global_context": {"request_id": "it-1", "state": {}, "metadata": {}}}
                 rsp = await session.call_tool(HookType.TOOL_PRE_INVOKE, {"plugin_name": "MyExternal", "payload": payload, "context": context})
                 txt = rsp.content[0].text
                 data = json.loads(txt)
                 assert "result" in data or "error" in data
     ```

- Gateway E2E smoke test with external plugin:
  1) Generate a token and export it (JWT helper):
     ```bash
     export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 60 --secret KEY)
     ```
  2) Ensure `.env` has `PLUGINS_ENABLED=true` and `plugins/config.yaml` includes your external plugin pointing to `http://localhost:8000/mcp`.
  3) Start gateway: `make serve`.
  4) Trigger a tool call (fires `tool_pre_invoke`):
     ```bash
     curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"jsonrpc":"2.0","id":1,"method":"example-tool","params":{"x":"y"}}' \
          http://localhost:4444/rpc
     ```

- Performance and timeouts:
  - To test timeout handling, configure `plugin_settings.plugin_timeout` low (e.g., 1–2s) and create a test plugin that `await asyncio.sleep(timeout+ε)` inside a hook, then assert the manager error behavior per mode/settings.
  - Use `pytest.mark.slow` sparingly; default tests should be fast and deterministic.
