## JavaScript Unit Testing

MCP Gateway uses **Vitest** for JavaScript unit testing, providing fast and modern testing capabilities for browser-based code. Tests cover pure/near-pure utility functions in `admin.js` (validation, formatting, parsing, error handling, display, and config).

### Configuration Files

- **`vitest.config.js`** - Main Vitest configuration (Istanbul coverage, JSDOM environment)
- **`tests/js/helpers/admin-env.js`** - Shared JSDOM + Istanbul instrumentation helper

### Running JavaScript Tests

```bash
# Run all tests
npm test
# or: make test-js

# Run with coverage report
npm run test:coverage
# or: make test-js-coverage

# Watch mode (auto-rerun on changes)
npm run test:watch

# Interactive UI mode
npm run test:ui
```

### Test Structure

JavaScript tests are located in the `tests/js/` directory, organized by category:

```
tests/
└── js/
    ├── helpers/
    │   └── admin-env.js               # Shared JSDOM + Istanbul setup
    ├── admin.test.js                   # escapeHtml (13 tests)
    ├── admin-validation.test.js        # Input/URL/JSON/IP/cert validators (92 tests)
    ├── admin-formatting.test.js        # formatValue/Number/Date/FileSize/etc. (46 tests)
    ├── admin-parsing.test.js           # parseUriTemplate/ThinkTags/CertInfo/KPI (47 tests)
    ├── admin-display.test.js           # Log/severity classes, status badges (39 tests)
    ├── admin-config.test.js            # isAdminUser, getRootPath, aggregation (27 tests)
    └── admin-errors.test.js            # handleFetchError (7 tests)
```

**Total: 271 tests across 7 test files.**

### Writing Tests

Tests use Vitest's Jest-compatible API with the shared helper for JSDOM setup:

```javascript
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { loadAdminJs, cleanupAdminJs } from './helpers/admin-env.js';

let win;

beforeAll(() => {
  win = loadAdminJs();
});

afterAll(() => {
  cleanupAdminJs();
});

describe('myFunction', () => {
  test('should do something', () => {
    expect(win.myFunction('input')).toBe('expected output');
  });
});
```

### Coverage

admin.js is a ~31K-line non-modular browser script. Tests cover all pure/near-pure utility functions:

| Metric | Coverage |
|--------|----------|
| Statements | 6.29% |
| Branches | 4.51% |
| Functions | 8.93% |
| Lines | 6.32% |

The remaining ~93% is DOM manipulation, fetch calls, Chart.js rendering, and HTMX event handlers that require full browser mocking or integration tests.

---

## Python Unit Testing

|                                            filepath                                             | passed | skipped | SUBTOTAL |
| ----------------------------------------------------------------------------------------------- | -----: | ------: | -------: |
| tests/differential/test_pii_filter_differential.py                                              |      0 |      32 |       32 |
| tests/e2e/test_admin_apis.py                                                                    |     32 |       1 |       33 |
| tests/e2e/test_main_apis.py                                                                     |    110 |       1 |      111 |
| tests/e2e/test_translate_dynamic_env_e2e.py                                                     |      1 |      14 |       15 |
| tests/integration/test_a2a_sdk_integration.py                                                   |      0 |      23 |       23 |
| tests/integration/test_concurrency_row_locking.py                                               |      0 |      41 |       41 |
| tests/integration/test_cross_hook_context_sharing.py                                            |      0 |       6 |        6 |
| tests/integration/test_dcr_flow_integration.py                                                  |      0 |       8 |        8 |
| tests/integration/test_integration.py                                                           |      0 |       5 |        5 |
| tests/integration/test_llmchat_endpoints.py                                                     |      0 |      14 |       14 |
| tests/integration/test_mcp_session_pool_integration.py                                          |      0 |      12 |       12 |
| tests/integration/test_metadata_integration.py                                                  |      0 |       8 |        8 |
| tests/integration/test_rbac_ownership_http.py                                                   |      0 |      10 |       10 |
| tests/integration/test_resource_plugin_integration.py                                           |      0 |       5 |        5 |
| tests/integration/test_session_registry_redis_integration.py                                    |      0 |       1 |        1 |
| tests/integration/test_streamable_http_redis.py                                                 |      0 |       7 |        7 |
| tests/integration/test_tag_endpoints.py                                                         |      0 |      21 |       21 |
| tests/integration/test_tool_cancel_integration.py                                               |      0 |      13 |       13 |
| tests/integration/test_tools_pagination.py                                                      |      0 |       6 |        6 |
| tests/integration/test_translate_dynamic_env.py                                                 |      0 |      16 |       16 |
| tests/integration/test_translate_echo.py                                                        |      0 |      13 |       13 |
| tests/security/test_input_validation.py                                                         |     66 |       2 |       68 |
| tests/security/test_rpc_api.py                                                                  |      0 |       1 |        1 |
| tests/security/test_validation.py                                                               |     25 |       1 |       26 |
| tests/unit/mcpgateway/cache/test_session_registry_extended.py                                   |     27 |       3 |       30 |
| tests/unit/mcpgateway/middleware/test_http_auth_integration.py                                  |     18 |       6 |       24 |
| tests/unit/mcpgateway/middleware/test_rbac.py                                                   |     77 |       9 |       86 |
| tests/unit/mcpgateway/plugins/plugins/altk_json_processor/test_json_processor.py                |      0 |       1 |        1 |
| tests/unit/mcpgateway/plugins/plugins/sparc_static_validator/test_sparc_static_validator.py     |      4 |      32 |       36 |
| tests/unit/mcpgateway/plugins/test_pii_filter_rust.py                                           |      1 |      44 |       45 |
| tests/unit/mcpgateway/plugins/tools/test_cli.py                                                 |      8 |       1 |        9 |
| tests/unit/mcpgateway/routers/test_reverse_proxy.py                                             |     65 |       1 |       66 |
| tests/unit/mcpgateway/routers/test_teams.py                                                     |     39 |       5 |       44 |
| tests/unit/mcpgateway/services/test_email_auth_basic.py                                         |    103 |       3 |      106 |
| tests/unit/mcpgateway/services/test_event_service.py                                            |     22 |       5 |       27 |
| tests/unit/mcpgateway/services/test_gateway_service.py                                          |    271 |       1 |      272 |
| tests/unit/mcpgateway/services/test_gateway_service_extended.py                                 |     37 |       1 |       38 |
| tests/unit/mcpgateway/services/test_mcp_client_chat_service_extended.py                         |    101 |       1 |      102 |
| tests/unit/mcpgateway/services/test_row_level_locking.py                                        |     16 |       2 |       18 |
| tests/unit/mcpgateway/services/test_team_invitation_service.py                                  |     37 |       4 |       41 |
| tests/unit/mcpgateway/test_observability.py                                                     |     31 |       1 |       32 |
| tests/unit/mcpgateway/test_postgresql_schema_config.py                                          |     14 |       2 |       16 |
| tests/unit/mcpgateway/test_ui_version.py                                                        |      0 |       1 |        1 |
| tests/unit/mcpgateway/tools/builder/test_dagger_deploy.py                                       |      0 |      20 |       20 |
| tests/unit/mcpgateway/validation/test_validators_advanced.py                                    |    102 |       3 |      105 |
| tests/async/test_async_safety.py                                                                |      3 |       0 |        3 |
| tests/e2e/test_admin_mcp_pool_metrics.py                                                        |     14 |       0 |       14 |
| tests/e2e/test_oauth_protected_resource.py                                                      |     17 |       0 |       17 |
| tests/e2e/test_session_pool_e2e.py                                                              |     34 |       0 |       34 |
| tests/security/test_configurable_headers.py                                                     |      6 |       0 |        6 |
| tests/security/test_rpc_input_validation.py                                                     |     14 |       0 |       14 |
| tests/security/test_security_cookies.py                                                         |     19 |       0 |       19 |
| tests/security/test_rpc_endpoint_validation.py                                                  |      5 |       0 |        5 |
| tests/security/test_security_headers.py                                                         |     21 |       0 |       21 |
| tests/security/test_security_middleware_comprehensive.py                                        |     49 |       0 |       49 |
| tests/security/test_security_performance_compatibility.py                                       |     29 |       0 |       29 |
| tests/security/test_standalone_middleware.py                                                    |      4 |       0 |        4 |
| tests/test_readme.py                                                                            |      1 |       0 |        1 |
| tests/unit/mcpgateway/cache/test_admin_stats_cache.py                                           |     17 |       0 |       17 |
| tests/unit/mcpgateway/cache/test_auth_cache_l1_l2.py                                            |     63 |       0 |       63 |
| tests/unit/mcpgateway/cache/test_cache_invalidation_subscriber.py                               |     20 |       0 |       20 |
| tests/unit/mcpgateway/cache/test_registry_cache.py                                              |     35 |       0 |       35 |
| tests/unit/mcpgateway/cache/test_resource_cache.py                                              |     12 |       0 |       12 |
| tests/unit/mcpgateway/cache/test_session_registry.py                                            |     68 |       0 |       68 |
| tests/unit/mcpgateway/cache/test_session_registry_coverage.py                                   |     63 |       0 |       63 |
| tests/unit/mcpgateway/cache/test_tool_lookup_cache.py                                           |     19 |       0 |       19 |
| tests/unit/mcpgateway/db/test_observability_migrations.py                                       |     39 |       0 |       39 |
| tests/unit/mcpgateway/handlers/test_sampling.py                                                 |     27 |       0 |       27 |
| tests/unit/mcpgateway/instrumentation/test_sqlalchemy.py                                        |     14 |       0 |       14 |
| tests/unit/mcpgateway/middleware/test_auth_method_propagation.py                                |      2 |       0 |        2 |
| tests/unit/mcpgateway/middleware/test_auth_middleware.py                                        |     11 |       0 |       11 |
| tests/unit/mcpgateway/middleware/test_compression.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/middleware/test_correlation_id.py                                         |     10 |       0 |       10 |
| tests/unit/mcpgateway/middleware/test_db_query_logging.py                                       |     12 |       0 |       12 |
| tests/unit/mcpgateway/middleware/test_http_auth_headers.py                                      |     25 |       0 |       25 |
| tests/unit/mcpgateway/middleware/test_observability_middleware.py                               |      6 |       0 |        6 |
| tests/unit/mcpgateway/middleware/test_path_filter.py                                            |     85 |       0 |       85 |
| tests/unit/mcpgateway/middleware/test_protocol_version.py                                       |      3 |       0 |        3 |
| tests/unit/mcpgateway/middleware/test_request_logging_middleware.py                             |     51 |       0 |       51 |
| tests/unit/mcpgateway/middleware/test_request_context.py                                        |      1 |       0 |        1 |
| tests/unit/mcpgateway/middleware/test_security_headers_middleware.py                            |     16 |       0 |       16 |
| tests/unit/mcpgateway/middleware/test_token_scoping.py                                          |     35 |       0 |       35 |
| tests/unit/mcpgateway/middleware/test_token_scoping_extra.py                                    |     40 |       0 |       40 |
| tests/unit/mcpgateway/middleware/test_validation_middleware.py                                  |     20 |       0 |       20 |
| tests/unit/mcpgateway/plugins/agent/test_agent_plugins.py                                       |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/proto/test_plugin_service_pb2_grpc.py     |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/server/test_runtime.py                    |     22 |       0 |       22 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/server/test_server.py                     |     20 |       0 |       20 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/test_client.py                            |     25 |       0 |       25 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/test_client_integration.py                |      7 |       0 |        7 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/test_grpc_models.py                       |     42 |       0 |       42 |
| tests/unit/mcpgateway/plugins/framework/external/grpc/test_tls_utils.py                         |     24 |       0 |       24 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_runtime.py                     |     16 |       0 |       16 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_runtime_coverage.py            |     10 |       0 |       10 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_server.py                      |     32 |       0 |       32 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_certificate_validation.py      |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_config.py                      |     16 |       0 |       16 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_coverage.py                    |     22 |       0 |       22 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_tls_utils.py                          |     27 |       0 |       27 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_stdio.py                       |      7 |       0 |        7 |
| tests/unit/mcpgateway/plugins/framework/external/test_proto_convert.py                          |     46 |       0 |       46 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_streamable_http.py             |      4 |       0 |        4 |
| tests/unit/mcpgateway/plugins/framework/external/unix/test_client.py                            |     30 |       0 |       30 |
| tests/unit/mcpgateway/plugins/framework/external/unix/test_protocol.py                          |     17 |       0 |       17 |
| tests/unit/mcpgateway/plugins/framework/external/unix/test_runtime.py                           |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/framework/external/unix/test_server.py                            |     28 |       0 |       28 |
| tests/unit/mcpgateway/plugins/framework/hooks/test_hook_patterns.py                             |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/framework/hooks/test_hook_registry.py                             |     12 |       0 |       12 |
| tests/unit/mcpgateway/plugins/framework/hooks/test_http.py                                      |     42 |       0 |       42 |
| tests/unit/mcpgateway/plugins/framework/external/unix/test_client_integration.py                |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/framework/loader/test_plugin_loader.py                            |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/framework/test_context.py                                         |      2 |       0 |        2 |
| tests/unit/mcpgateway/plugins/framework/test_errors.py                                          |      3 |       0 |        3 |
| tests/unit/mcpgateway/plugins/framework/test_manager.py                                         |     12 |       0 |       12 |
| tests/unit/mcpgateway/plugins/framework/test_manager_coverage.py                                |     11 |       0 |       11 |
| tests/unit/mcpgateway/plugins/framework/test_manager_extended.py                                |     16 |       0 |       16 |
| tests/unit/mcpgateway/plugins/framework/test_memory.py                                          |     80 |       0 |       80 |
| tests/unit/mcpgateway/plugins/framework/test_models_tls.py                                      |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_base.py                                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_base_coverage.py                            |     22 |       0 |       22 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_models.py                                   |     25 |       0 |       25 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_models_coverage.py                          |     27 |       0 |       27 |
| tests/unit/mcpgateway/plugins/framework/test_registry.py                                        |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/framework/test_resource_hooks.py                                  |     13 |       0 |       13 |
| tests/unit/mcpgateway/plugins/framework/test_utils.py                                           |     11 |       0 |       11 |
| tests/unit/mcpgateway/plugins/plugins/argument_normalizer/test_argument_normalizer.py           |      4 |       0 |        4 |
| tests/unit/mcpgateway/plugins/plugins/cached_tool_result/test_cached_tool_result.py             |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/code_safety_linter/test_code_safety_linter.py             |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation.py             |     17 |       0 |       17 |
| tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/plugins/external_clamav/test_clamav_remote.py                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/plugins/html_to_markdown/test_html_to_markdown.py                 |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/file_type_allowlist/test_file_type_allowlist.py           |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/markdown_cleaner/test_markdown_cleaner.py                 |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/json_repair/test_json_repair.py                           |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/output_length_guard/test_output_length_guard.py           |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py                             |     18 |       0 |       18 |
| tests/unit/mcpgateway/plugins/plugins/resource_filter/test_resource_filter.py                   |     15 |       0 |       15 |
| tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py                         |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/response_cache_by_prompt/test_response_cache_by_prompt.py |     19 |       0 |       19 |
| tests/unit/mcpgateway/plugins/plugins/schema_guard/test_schema_guard.py                         |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/test_init_hooks_plugins.py                                |    107 |       0 |      107 |
| tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py                     |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin.py                                |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin_smoke.py                          |      3 |       0 |        3 |
| tests/unit/mcpgateway/plugins/plugins/virus_total_checker/test_virus_total_checker.py           |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py          |      4 |       0 |        4 |
| tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_notification.py         |     14 |       0 |       14 |
| tests/unit/mcpgateway/routers/test_auth.py                                                      |     15 |       0 |       15 |
| tests/unit/mcpgateway/routers/test_cancellation_router.py                                       |     13 |       0 |       13 |
| tests/unit/mcpgateway/routers/test_email_auth_helpers.py                                        |      8 |       0 |        8 |
| tests/unit/mcpgateway/routers/test_email_auth_router.py                                         |     62 |       0 |       62 |
| tests/unit/mcpgateway/routers/test_llm_admin_router.py                                          |     38 |       0 |       38 |
| tests/unit/mcpgateway/routers/test_llm_config_router.py                                         |     32 |       0 |       32 |
| tests/unit/mcpgateway/routers/test_llm_proxy_router.py                                          |     10 |       0 |       10 |
| tests/unit/mcpgateway/routers/test_llmchat_router.py                                            |     68 |       0 |       68 |
| tests/unit/mcpgateway/routers/test_log_search.py                                                |     12 |       0 |       12 |
| tests/unit/mcpgateway/routers/test_log_search_helpers.py                                        |      4 |       0 |        4 |
| tests/unit/mcpgateway/routers/test_oauth_router.py                                              |     59 |       0 |       59 |
| tests/unit/mcpgateway/routers/test_observability_sql.py                                         |     19 |       0 |       19 |
| tests/unit/mcpgateway/routers/test_metrics_maintenance.py                                       |     10 |       0 |       10 |
| tests/unit/mcpgateway/routers/test_rbac_router.py                                               |     18 |       0 |       18 |
| tests/unit/mcpgateway/routers/test_sso_router.py                                                |     33 |       0 |       33 |
| tests/unit/mcpgateway/routers/test_teams_coverage.py                                            |     42 |       0 |       42 |
| tests/unit/mcpgateway/routers/test_teams_v2.py                                                  |     10 |       0 |       10 |
| tests/unit/mcpgateway/routers/test_tokens.py                                                    |     38 |       0 |       38 |
| tests/unit/mcpgateway/routers/test_well_known.py                                                |     37 |       0 |       37 |
| tests/unit/mcpgateway/services/test_a2a_query_param_auth.py                                     |      9 |       0 |        9 |
| tests/unit/mcpgateway/services/test_a2a_service.py                                              |     92 |       0 |       92 |
| tests/unit/mcpgateway/services/test_argon2_service.py                                           |     61 |       0 |       61 |
| tests/unit/mcpgateway/services/test_async_crypto_wrappers.py                                    |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_audit_trail_service.py                                      |      6 |       0 |        6 |
| tests/unit/mcpgateway/services/test_authorization_access.py                                     |     34 |       0 |       34 |
| tests/unit/mcpgateway/services/test_cancellation_service.py                                     |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_catalog_service.py                                          |     44 |       0 |       44 |
| tests/unit/mcpgateway/services/test_completion_service.py                                       |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_correlation_id_json_formatter.py                            |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_dcr_service.py                                              |     30 |       0 |       30 |
| tests/unit/mcpgateway/services/test_elicitation_service.py                                      |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_encryption_service.py                                       |     22 |       0 |       22 |
| tests/unit/mcpgateway/services/test_export_service.py                                           |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_gateway_auto_refresh.py                                     |      9 |       0 |        9 |
| tests/unit/mcpgateway/services/test_gateway_explicit_health_rpc.py                              |      6 |       0 |        6 |
| tests/unit/mcpgateway/services/test_gateway_query_param_auth.py                                 |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_gateway_resources_prompts.py                                |      8 |       0 |        8 |
| tests/unit/mcpgateway/services/test_gateway_service_health_oauth.py                             |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_gateway_service_helpers.py                                  |      8 |       0 |        8 |
| tests/unit/mcpgateway/services/test_gateway_service_oauth_comprehensive.py                      |     30 |       0 |       30 |
| tests/unit/mcpgateway/services/test_grpc_service.py                                             |     17 |       0 |       17 |
| tests/unit/mcpgateway/services/test_gateway_validation_redirects.py                             |      2 |       0 |        2 |
| tests/unit/mcpgateway/services/test_grpc_service_no_grpc.py                                     |     27 |       0 |       27 |
| tests/unit/mcpgateway/services/test_http_client_service.py                                      |     20 |       0 |       20 |
| tests/unit/mcpgateway/services/test_import_service.py                                           |    146 |       0 |      146 |
| tests/unit/mcpgateway/services/test_llm_provider_service.py                                     |     41 |       0 |       41 |
| tests/unit/mcpgateway/services/test_llm_proxy_service.py                                        |     61 |       0 |       61 |
| tests/unit/mcpgateway/services/test_log_aggregator.py                                           |     52 |       0 |       52 |
| tests/unit/mcpgateway/services/test_log_aggregator_helpers.py                                   |      2 |       0 |        2 |
| tests/unit/mcpgateway/services/test_log_storage_service.py                                      |     28 |       0 |       28 |
| tests/unit/mcpgateway/services/test_logging_service.py                                          |      7 |       0 |        7 |
| tests/unit/mcpgateway/services/test_logging_service_comprehensive.py                            |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_mcp_chat_history_extra.py                                   |      3 |       0 |        3 |
| tests/unit/mcpgateway/services/test_mcp_client_chat_service.py                                  |     56 |       0 |       56 |
| tests/unit/mcpgateway/services/test_mcp_session_pool.py                                         |     69 |       0 |       69 |
| tests/unit/mcpgateway/services/test_mcp_session_pool_coverage.py                                |    131 |       0 |      131 |
| tests/unit/mcpgateway/services/test_metrics.py                                                  |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_metrics_buffer_service.py                                   |     44 |       0 |       44 |
| tests/unit/mcpgateway/services/test_metrics_cleanup_service.py                                  |     17 |       0 |       17 |
| tests/unit/mcpgateway/services/test_metrics_query_service.py                                    |     39 |       0 |       39 |
| tests/unit/mcpgateway/services/test_metrics_rollup_service.py                                   |     34 |       0 |       34 |
| tests/unit/mcpgateway/services/test_notification_service.py                                     |     38 |       0 |       38 |
| tests/unit/mcpgateway/services/test_oauth_manager.py                                            |     50 |       0 |       50 |
| tests/unit/mcpgateway/services/test_oauth_manager_pkce.py                                       |    115 |       0 |      115 |
| tests/unit/mcpgateway/services/test_observability_service.py                                    |     59 |       0 |       59 |
| tests/unit/mcpgateway/services/test_performance_service.py                                      |     44 |       0 |       44 |
| tests/unit/mcpgateway/services/test_performance_tracker.py                                      |     25 |       0 |       25 |
| tests/unit/mcpgateway/services/test_permission_fallback.py                                      |     15 |       0 |       15 |
| tests/unit/mcpgateway/services/test_permission_service.py                                       |     57 |       0 |       57 |
| tests/unit/mcpgateway/services/test_permission_service_comprehensive.py                         |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_personal_team_service.py                                    |     27 |       0 |       27 |
| tests/unit/mcpgateway/services/test_plugin_service.py                                           |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_prompt_service.py                                           |     97 |       0 |       97 |
| tests/unit/mcpgateway/services/test_prompt_service_extended.py                                  |     24 |       0 |       24 |
| tests/unit/mcpgateway/services/test_resource_ownership.py                                       |     16 |       0 |       16 |
| tests/unit/mcpgateway/services/test_resource_service.py                                         |    140 |       0 |      140 |
| tests/unit/mcpgateway/services/test_resource_service_plugins.py                                 |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_role_service.py                                             |     66 |       0 |       66 |
| tests/unit/mcpgateway/services/test_root_service.py                                             |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_security_logger.py                                          |     33 |       0 |       33 |
| tests/unit/mcpgateway/services/test_server_service.py                                           |     78 |       0 |       78 |
| tests/unit/mcpgateway/services/test_sso_admin_assignment.py                                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/services/test_sso_approval_workflow.py                                    |      4 |       0 |        4 |
| tests/unit/mcpgateway/services/test_sso_entra_role_mapping.py                                   |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_sso_service.py                                              |     74 |       0 |       74 |
| tests/unit/mcpgateway/services/test_sso_user_normalization.py                                   |     25 |       0 |       25 |
| tests/unit/mcpgateway/services/test_structured_logger.py                                        |     48 |       0 |       48 |
| tests/unit/mcpgateway/services/test_support_bundle_service.py                                   |     15 |       0 |       15 |
| tests/unit/mcpgateway/services/test_system_stats_service.py                                     |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_tag_service.py                                              |     26 |       0 |       26 |
| tests/unit/mcpgateway/services/test_team_invitation_service_coverage.py                         |      8 |       0 |        8 |
| tests/unit/mcpgateway/services/test_team_management_service.py                                  |    105 |       0 |      105 |
| tests/unit/mcpgateway/services/test_team_management_service_coverage.py                         |     62 |       0 |       62 |
| tests/unit/mcpgateway/services/test_token_catalog_service.py                                    |     75 |       0 |       75 |
| tests/unit/mcpgateway/services/test_token_storage_service.py                                    |     40 |       0 |       40 |
| tests/unit/mcpgateway/services/test_tool_service.py                                             |    174 |       0 |      174 |
| tests/unit/mcpgateway/services/test_tool_service_coverage.py                                    |    235 |       0 |      235 |
| tests/unit/mcpgateway/services/test_tool_service_helpers.py                                     |      3 |       0 |        3 |
| tests/unit/mcpgateway/test_admin.py                                                             |    737 |       0 |      737 |
| tests/unit/mcpgateway/test_admin_error_handlers.py                                              |      9 |       0 |        9 |
| tests/unit/mcpgateway/test_admin_catalog_htmx.py                                                |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_import_export.py                                               |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_metrics_helpers.py                                             |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_module.py                                                      |     38 |       0 |       38 |
| tests/unit/mcpgateway/test_admin_observability_sql.py                                           |     27 |       0 |       27 |
| tests/unit/mcpgateway/test_auth.py                                                              |     81 |       0 |       81 |
| tests/unit/mcpgateway/test_auth_helpers.py                                                      |     13 |       0 |       13 |
| tests/unit/mcpgateway/test_bootstrap_db.py                                                      |     35 |       0 |       35 |
| tests/unit/mcpgateway/test_cli.py                                                               |      9 |       0 |        9 |
| tests/unit/mcpgateway/test_cli_config_schema.py                                                 |     14 |       0 |       14 |
| tests/unit/mcpgateway/test_cli_export_import_coverage.py                                        |     32 |       0 |       32 |
| tests/unit/mcpgateway/test_config.py                                                            |     80 |       0 |       80 |
| tests/unit/mcpgateway/test_coverage_push.py                                                     |     13 |       0 |       13 |
| tests/unit/mcpgateway/test_db.py                                                                |    149 |       0 |      149 |
| tests/unit/mcpgateway/test_db_isready.py                                                        |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_display_name_uuid_features.py                                        |     28 |       0 |       28 |
| tests/unit/mcpgateway/test_final_coverage_push.py                                               |     24 |       0 |       24 |
| tests/unit/mcpgateway/test_issue_840_a2a_agent.py                                               |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_llm_schemas.py                                                       |     40 |       0 |       40 |
| tests/unit/mcpgateway/test_main.py                                                              |    204 |       0 |      204 |
| tests/unit/mcpgateway/test_main_error_handlers.py                                               |     29 |       0 |       29 |
| tests/unit/mcpgateway/test_main_extended.py                                                     |    213 |       0 |      213 |
| tests/unit/mcpgateway/test_main_helpers.py                                                      |     12 |       0 |       12 |
| tests/unit/mcpgateway/test_main_helpers_extra.py                                                |      6 |       0 |        6 |
| tests/unit/mcpgateway/test_main_pool_init.py                                                    |      5 |       0 |        5 |
| tests/unit/mcpgateway/test_metrics.py                                                           |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_models.py                                                            |     25 |       0 |       25 |
| tests/unit/mcpgateway/test_multi_auth_headers.py                                                |     22 |       0 |       22 |
| tests/unit/mcpgateway/test_oauth_manager.py                                                     |    117 |       0 |      117 |
| tests/unit/mcpgateway/test_performance_schemas.py                                               |     24 |       0 |       24 |
| tests/unit/mcpgateway/test_reverse_proxy.py                                                     |     67 |       0 |       67 |
| tests/unit/mcpgateway/test_rpc_backward_compatibility.py                                        |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_rpc_tool_invocation.py                                               |     12 |       0 |       12 |
| tests/unit/mcpgateway/test_schemas.py                                                           |     60 |       0 |       60 |
| tests/unit/mcpgateway/test_schemas_auth_validation.py                                           |     27 |       0 |       27 |
| tests/unit/mcpgateway/test_schemas_validators_extra.py                                          |     40 |       0 |       40 |
| tests/unit/mcpgateway/test_settings_fields.py                                                   |     32 |       0 |       32 |
| tests/unit/mcpgateway/test_simple_coverage_boost.py                                             |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_streamable_closedresource_filter.py                                  |      1 |       0 |        1 |
| tests/unit/mcpgateway/test_toolops_altk_service.py                                              |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_toolops_utils.py                                                     |     12 |       0 |       12 |
| tests/unit/mcpgateway/test_translate.py                                                         |    149 |       0 |      149 |
| tests/unit/mcpgateway/test_translate_grpc.py                                                    |     39 |       0 |       39 |
| tests/unit/mcpgateway/test_translate_grpc_helpers.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_translate_header_utils.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_translate_helpers.py                                                 |      5 |       0 |        5 |
| tests/unit/mcpgateway/test_translate_stdio_endpoint.py                                          |     21 |       0 |       21 |
| tests/unit/mcpgateway/test_version.py                                                           |     21 |       0 |       21 |
| tests/unit/mcpgateway/test_validate_env.py                                                      |      2 |       0 |        2 |
| tests/unit/mcpgateway/test_well_known.py                                                        |     35 |       0 |       35 |
| tests/unit/mcpgateway/test_wrapper.py                                                           |     50 |       0 |       50 |
| tests/unit/mcpgateway/tools/builder/test_cli.py                                                 |     37 |       0 |       37 |
| tests/unit/mcpgateway/tools/builder/test_common.py                                              |     38 |       0 |       38 |
| tests/unit/mcpgateway/tools/builder/test_python_deploy.py                                       |     15 |       0 |       15 |
| tests/unit/mcpgateway/tools/builder/test_schema.py                                              |     29 |       0 |       29 |
| tests/unit/mcpgateway/transports/test_redis_event_store.py                                      |     10 |       0 |       10 |
| tests/unit/mcpgateway/transports/test_sse_transport.py                                          |     23 |       0 |       23 |
| tests/unit/mcpgateway/transports/test_stdio_transport.py                                        |     11 |       0 |       11 |
| tests/unit/mcpgateway/transports/test_streamablehttp_transport.py                               |    170 |       0 |      170 |
| tests/unit/mcpgateway/transports/test_websocket_transport.py                                    |     15 |       0 |       15 |
| tests/unit/mcpgateway/utils/test_analyze_query_log.py                                           |      9 |       0 |        9 |
| tests/unit/mcpgateway/utils/test_correlation_id.py                                              |     18 |       0 |       18 |
| tests/unit/mcpgateway/utils/test_create_jwt_token.py                                            |     22 |       0 |       22 |
| tests/unit/mcpgateway/utils/test_db_isready.py                                                  |     10 |       0 |       10 |
| tests/unit/mcpgateway/utils/test_error_formatter.py                                             |     23 |       0 |       23 |
| tests/unit/mcpgateway/utils/test_generate_keys.py                                               |      4 |       0 |        4 |
| tests/unit/mcpgateway/utils/test_jwt_config_helper.py                                           |     21 |       0 |       21 |
| tests/unit/mcpgateway/utils/test_keycloak_discovery.py                                          |      8 |       0 |        8 |
| tests/unit/mcpgateway/utils/test_metadata_capture.py                                            |     32 |       0 |       32 |
| tests/unit/mcpgateway/utils/test_orjson_response.py                                             |     29 |       0 |       29 |
| tests/unit/mcpgateway/utils/test_metrics_common.py                                              |      2 |       0 |        2 |
| tests/unit/mcpgateway/utils/test_pagination.py                                                  |     53 |       0 |       53 |
| tests/unit/mcpgateway/utils/test_passthrough_headers.py                                         |     20 |       0 |       20 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_fixed.py                                   |     29 |       0 |       29 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_security.py                                |     18 |       0 |       18 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_source.py                                  |      8 |       0 |        8 |
| tests/unit/mcpgateway/utils/test_proxy_auth.py                                                  |     23 |       0 |       23 |
| tests/unit/mcpgateway/utils/test_psycopg3_optimizations.py                                      |     17 |       0 |       17 |
| tests/unit/mcpgateway/utils/test_redis_client.py                                                |     25 |       0 |       25 |
| tests/unit/mcpgateway/utils/test_redis_isready.py                                               |     12 |       0 |       12 |
| tests/unit/mcpgateway/utils/test_retry_manager.py                                               |     48 |       0 |       48 |
| tests/unit/mcpgateway/utils/test_security_cookies.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/utils/test_services_auth.py                                               |      8 |       0 |        8 |
| tests/unit/mcpgateway/utils/test_small_utils.py                                                 |      4 |       0 |        4 |
| tests/unit/mcpgateway/utils/test_sqlalchemy_modifier.py                                         |     32 |       0 |       32 |
| tests/unit/mcpgateway/utils/test_ssl_context_cache.py                                           |      4 |       0 |        4 |
| tests/unit/mcpgateway/utils/test_ssl_key_manager.py                                             |     10 |       0 |       10 |
| tests/unit/mcpgateway/utils/test_sso_bootstrap.py                                               |     13 |       0 |       13 |
| tests/unit/mcpgateway/utils/test_token_scoping_utils.py                                         |      7 |       0 |        7 |
| tests/unit/mcpgateway/utils/test_url_auth.py                                                    |     30 |       0 |       30 |
| tests/unit/mcpgateway/utils/test_validate_signature.py                                          |     18 |       0 |       18 |
| tests/unit/mcpgateway/utils/test_verify_credentials.py                                          |     59 |       0 |       59 |
| tests/unit/mcpgateway/validation/test_jsonrpc.py                                                |      7 |       0 |        7 |
| tests/unit/mcpgateway/validation/test_tags.py                                                   |     16 |       0 |       16 |
| tests/unit/mcpgateway/validation/test_validators.py                                             |     31 |       0 |       31 |
| tests/unit/plugins/test_circuit_breaker.py                                                      |     20 |       0 |       20 |
| tests/unit/plugins/test_secrets_detection.py                                                    |      8 |       0 |        8 |
| tests/unit/plugins/test_unified_pdp.py                                                          |     46 |       0 |       46 |
| tests/unit/plugins/test_unified_pdp_plugin.py                                                   |     14 |       0 |       14 |
| tests/unit/plugins/toon_encoder/test_toon.py                                                    |    102 |       0 |      102 |
| tests/unit/plugins/toon_encoder/test_toon_encoder.py                                            |     21 |       0 |       21 |
| tests/unit/test_session_registry_redis_broadcast.py                                             |      1 |       0 |        1 |
| TOTAL                                                                                           |  10719 |     407 |    11126 |

## Coverage report

| Name                                                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| mcpgateway/admin.py                                                            |     5687 |        0 |     1560 |      104 |     99% |225->231, 1320->1326, 1579->1581, 1800->1803, 1803->1814, 1974->1977, 1977->1988, 2625->2620, 3006->3013, 3016->3027, 3334->3345, 3685->3688, 3841->3844, 3877->3881, 3964->3967, 4105->4107, 4578->4596, 4792->4771, 5089->5093, 5708->5702, 6007->6014, 6096->6102, 6102->6108, 6108->6114, 6114->6120, 6242->6246, 6254->6257, 6603->6618, 6646->6650, 6798->6811, 6811->6814, 6828->6830, 6913->6918, 6920->6936, 7010->7024, 7024->7030, 7142->7155, 7179->7181, 7216->7221, 7360->7362, 7481->7487, 7552->7558, 7641->7647, 7714->7720, 7829->7845, 7869->7871, 7906->7911, 8010->8023, 8023->8029, 8092->8105, 8105->8111, 8183->8196, 8196->8202, 8289->8302, 8302->8308, 8445->8447, 8457->8459, 8482->8487, 8582->8588, 8605->8607, 8653->8659, 8676->8678, 8987->8990, 8990->8992, 9538->9540, 10627->10630, 11311->11322, 11668->11678, 11670->11678, 11766->11806, 11919->11940, 12463->12465, 12659->12666, 12685->12693, 12709->12711, 12711->12713, 12713->12715, 12715->12717, 12717->12719, 12719->12721, 12721->12727, 12727->12729, 12729->12733, 12733->12738, 12735->12738, 13146->13150, 13275->13279, 13330->13334, 13388->13392, 13441->13445, 13569->13573, 13639->13643, 13702->13706, 14678->14680, 14680->14682, 14682->14684, 14684->14687, 14951->14948, 15094->15083, 15201->15198, 15798->15797, 16333->16335, 16335->16337, 16338->16337 |
| mcpgateway/auth.py                                                             |      448 |       54 |      184 |        7 |     89% |160-173, 210-246, 262-289, 671, 795->798, 889-890, 954-959, 996, 1084-1085, 1092 |
| mcpgateway/bootstrap\_db.py                                                    |      259 |       35 |       76 |        7 |     86% |118-124, 127-136, 189->191, 193-194, 198->201, 272->276, 302-303, 347-348, 352-355, 442-444, 503-507, 517-518, 543-546 |
| mcpgateway/cache/a2a\_stats\_cache.py                                          |       40 |        2 |        4 |        1 |     93% |   155-156 |
| mcpgateway/cache/admin\_stats\_cache.py                                        |      370 |        0 |       98 |        1 |     99% |  182->186 |
| mcpgateway/cache/auth\_cache.py                                                |      441 |        0 |      118 |        0 |    100% |           |
| mcpgateway/cache/global\_config\_cache.py                                      |       58 |        2 |       12 |        1 |     96% |   147-148 |
| mcpgateway/cache/metrics\_cache.py                                             |       67 |        4 |        8 |        0 |     95% |227-228, 243-244 |
| mcpgateway/cache/registry\_cache.py                                            |      308 |       20 |       68 |        9 |     92% |242->246, 600->exit, 608-609, 627->630, 630->638, 634-635, 638->657, 642-645, 649-654, 665, 671->663, 673->675, 675->663, 679-683 |
| mcpgateway/cache/resource\_cache.py                                            |       94 |        2 |       18 |        1 |     97% |  272, 332 |
| mcpgateway/cache/session\_registry.py                                          |      758 |       84 |      232 |       13 |     89% |356-357, 496->511, 506->511, 541->549, 558->566, 575->584, 744->746, 780->782, 968->exit, 1185-1251, 1253->exit, 1305-1325, 1349-1358, 1426-1427, 1441, 1446->1462, 1463-1467, 1474-1476, 1966-1967 |
| mcpgateway/cache/tool\_lookup\_cache.py                                        |      168 |        4 |       42 |        5 |     96% |154->157, 159->162, 275->exit, 279-280, 332->334, 335-336, 372->375 |
| mcpgateway/cli.py                                                              |      105 |       10 |       34 |        5 |     88% |120->123, 295->347, 299-301, 304-306, 331-335 |
| mcpgateway/cli\_export\_import.py                                              |      178 |       16 |       62 |        4 |     90% |90-112, 207->206, 248->251, 312->316 |
| mcpgateway/common/models.py                                                    |      344 |        1 |        2 |        1 |     99% |       925 |
| mcpgateway/common/validators.py                                                |      351 |       12 |      210 |       11 |     96% |406, 488, 597, 815, 1019, 1037, 1041->1051, 1047->1051, 1064, 1069-1070, 1153-1154, 1165, 1188->1168 |
| mcpgateway/config.py                                                           |      839 |       10 |      128 |        8 |     98% |648->654, 691, 726, 767, 769, 1699, 2074, 2124-2128 |
| mcpgateway/db.py                                                               |     2164 |        1 |      378 |       22 |     99% |55, 98->102, 107->119, 642->646, 685->674, 689->693, 730->720, 734->737, 1003->1000, 1238->1237, 1968->1971, 3118->3120, 3121->3111, 3490->3492, 3493->3483, 3901->3903, 3904->3894, 4206->4208, 4209->4199, 5237->5241, 6230->6235, 6286->6291 |
| mcpgateway/handlers/sampling.py                                                |       88 |        1 |       44 |        2 |     98% |214, 514->518 |
| mcpgateway/instrumentation/sqlalchemy.py                                       |       95 |        4 |       22 |        5 |     92% |81->85, 115-116, 140->145, 216->222, 218-219, 313->exit, 316->exit |
| mcpgateway/llm\_provider\_configs.py                                           |       60 |        0 |        0 |        0 |    100% |           |
| mcpgateway/llm\_schemas.py                                                     |      228 |        0 |        6 |        0 |    100% |           |
| mcpgateway/main.py                                                             |     2845 |        0 |      838 |       43 |     99% |329->324, 429->435, 614->619, 685->693, 1003->1006, 1009->1015, 1016->1018, 1018->1021, 1030->exit, 1050->exit, 1089->1092, 1260->1262, 1264->1266, 1318->1325, 1323->1325, 1450->1452, 1518->1543, 1529->1543, 1546->1550, 1827->1834, 1875->1877, 1952->1972, 2297->2299, 2426->2428, 2758->2762, 2840->2859, 2843->2859, 3099->3101, 3565->3567, 4578->4580, 5069->5071, 5623->5643, 5648->5653, 5943->exit, 6046->6048, 6260->6264, 6384->6388, 6520->6524, 6553->6570, 6679->6682, 6840->6843, 6918->6922, 7109->7117 |
| mcpgateway/middleware/auth\_middleware.py                                      |       64 |        0 |       14 |        0 |    100% |           |
| mcpgateway/middleware/compression.py                                           |       22 |        0 |        4 |        0 |    100% |           |
| mcpgateway/middleware/correlation\_id.py                                       |       28 |        0 |        6 |        0 |    100% |           |
| mcpgateway/middleware/db\_query\_logging.py                                    |      183 |       27 |       60 |       13 |     80% |99, 160, 162, 170->180, 186->192, 187->186, 193, 199->201, 252-278, 294, 341, 361->365, 426, 427->431, 446-447 |
| mcpgateway/middleware/http\_auth\_middleware.py                                |       58 |        0 |       22 |        2 |     98% |90->95, 118->122 |
| mcpgateway/middleware/observability\_middleware.py                             |       94 |       13 |       22 |        8 |     82% |89->93, 96->102, 149-153, 163->175, 171-172, 175->188, 185-186, 192->211, 207-208, 211->218, 214-215, 224->226 |
| mcpgateway/middleware/path\_filter.py                                          |       61 |        4 |       10 |        0 |     94% |137-138, 153-154 |
| mcpgateway/middleware/protocol\_version.py                                     |       29 |        0 |       10 |        0 |    100% |           |
| mcpgateway/middleware/rbac.py                                                  |      299 |       10 |      132 |        2 |     95% |353-355, 543->550, 808-820 |
| mcpgateway/middleware/request\_context.py                                      |        7 |        0 |        2 |        0 |    100% |           |
| mcpgateway/middleware/request\_logging\_middleware.py                          |      227 |       11 |       82 |        4 |     95% |342->350, 386-387, 394->416, 413-414, 458->477, 475-476, 499-500, 570, 584->604, 601-602 |
| mcpgateway/middleware/security\_headers.py                                     |       61 |        0 |       40 |        0 |    100% |           |
| mcpgateway/middleware/token\_scoping.py                                        |      382 |       26 |      192 |       16 |     93% |160, 233->224, 382, 414-415, 427->429, 440->443, 513, 553, 673-674, 712-713, 736-737, 765-766, 778-779, 786-787, 796-799, 866-870, 880, 926->931 |
| mcpgateway/middleware/validation\_middleware.py                                |      100 |       11 |       52 |        7 |     87% |93-98, 118->123, 120, 130->exit, 196, 211, 213, 229->233, 238-239 |
| mcpgateway/observability.py                                                    |      238 |       18 |       98 |       16 |     90% |23-28, 68->97, 92-94, 163-164, 170-171, 185->184, 232->231, 245, 269->268, 281-282, 289-290, 297-298, 308->323, 450->453, 453->455, 455->462, 494->498, 514->516, 519->522 |
| mcpgateway/plugins/framework/base.py                                           |      153 |        0 |       42 |        2 |     99% |532->541, 555->exit |
| mcpgateway/plugins/framework/constants.py                                      |       26 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/decorator.py                                      |       21 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/errors.py                                         |       12 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/client.py                           |      108 |        0 |       26 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/proto/plugin\_service\_pb2.py       |       11 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/proto/plugin\_service\_pb2\_grpc.py |       58 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/server/runtime.py                   |       99 |        0 |       20 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/server/server.py                    |       88 |        0 |       16 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/tls\_utils.py                       |       44 |        0 |       10 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/mcp/client.py                            |      286 |       35 |       98 |       22 |     85% |81, 83->88, 85, 104-105, 108-114, 140, 149-151, 195->198, 200, 203->206, 206->exit, 222->224, 224->226, 238-240, 283, 286, 302-305, 311->exit, 371, 383->369, 389-391, 404, 409, 414-416, 423->425, 436->439, 439->441, 463-464 |
| mcpgateway/plugins/framework/external/mcp/server/runtime.py                    |      152 |       11 |       42 |        6 |     91% |133, 254->257, 259->262, 265->267, 309, 318-319, 327, 381, 392-393, 401, 493, 533 |
| mcpgateway/plugins/framework/external/mcp/server/server.py                     |       55 |        1 |       14 |        1 |     97% |       223 |
| mcpgateway/plugins/framework/external/mcp/tls\_utils.py                        |       27 |        0 |        8 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/proto\_convert.py                        |       70 |        0 |       36 |        1 |     99% |    48->52 |
| mcpgateway/plugins/framework/external/unix/client.py                           |      138 |        1 |       28 |        1 |     99% |       201 |
| mcpgateway/plugins/framework/external/unix/protocol.py                         |       28 |        0 |       10 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/unix/server/runtime.py                   |       22 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/unix/server/server.py                    |      179 |        6 |       36 |        5 |     95% |124->151, 155-156, 192->198, 246->248, 344->347, 359-360, 404-405 |
| mcpgateway/plugins/framework/hooks/agents.py                                   |       30 |        0 |        2 |        1 |     97% | 138->exit |
| mcpgateway/plugins/framework/hooks/http.py                                     |       57 |        0 |        2 |        1 |     98% | 205->exit |
| mcpgateway/plugins/framework/hooks/prompts.py                                  |       23 |        0 |        2 |        1 |     96% | 121->exit |
| mcpgateway/plugins/framework/hooks/registry.py                                 |       38 |        0 |       10 |        0 |    100% |           |
| mcpgateway/plugins/framework/hooks/resources.py                                |       22 |        0 |        2 |        1 |     96% | 111->exit |
| mcpgateway/plugins/framework/hooks/tools.py                                    |       24 |        0 |        2 |        1 |     96% | 114->exit |
| mcpgateway/plugins/framework/loader/config.py                                  |       18 |        0 |        2 |        0 |    100% |           |
| mcpgateway/plugins/framework/loader/plugin.py                                  |       53 |        2 |       18 |        3 |     93% |74->exit, 77, 123 |
| mcpgateway/plugins/framework/manager.py                                        |      218 |        7 |       78 |        6 |     96% |152, 257, 264->270, 285->293, 535-536, 585-586, 640 |
| mcpgateway/plugins/framework/memory.py                                         |       90 |        0 |       40 |        0 |    100% |           |
| mcpgateway/plugins/framework/models.py                                         |      572 |       34 |      228 |       28 |     92% |371, 373, 382, 417, 423, 438-439, 476-478, 509->512, 558, 574->583, 579, 581->583, 622, 627, 629, 647, 668, 674, 689-690, 884, 886, 890, 904-905, 981, 983, 987, 1001-1002, 1057->1060, 1103, 1105, 1199, 1232 |
| mcpgateway/plugins/framework/registry.py                                       |       66 |        0 |       18 |        1 |     99% |  151->155 |
| mcpgateway/plugins/framework/utils.py                                          |       52 |        1 |       30 |        2 |     96% |138, 239->249 |
| mcpgateway/plugins/tools/cli.py                                                |       51 |        3 |        2 |        0 |     94% |168-169, 224 |
| mcpgateway/plugins/tools/models.py                                             |        7 |        0 |        0 |        0 |    100% |           |
| mcpgateway/reverse\_proxy.py                                                   |      333 |       21 |       94 |       16 |     91% |52-53, 58-59, 65-66, 179->185, 226, 236, 247-250, 322, 352, 355->359, 360->362, 470->474, 472->474, 477, 548->559, 559->563, 573, 579, 712, 723, 767-768 |
| mcpgateway/routers/auth.py                                                     |       58 |        0 |        8 |        0 |    100% |           |
| mcpgateway/routers/cancellation\_router.py                                     |       45 |        3 |        6 |        1 |     92% |96-98, 126 |
| mcpgateway/routers/email\_auth.py                                              |      253 |        0 |       40 |        0 |    100% |           |
| mcpgateway/routers/llm\_admin\_router.py                                       |      226 |        0 |       42 |        3 |     99% |576->579, 722->725, 748->769 |
| mcpgateway/routers/llm\_config\_router.py                                      |      184 |        0 |        2 |        0 |    100% |           |
| mcpgateway/routers/llm\_proxy\_router.py                                       |       46 |        0 |        6 |        0 |    100% |           |
| mcpgateway/routers/llmchat\_router.py                                          |      337 |        5 |      106 |        7 |     97% |36-37, 571, 737->746, 740->738, 828->819, 920, 1022, 1151->1155 |
| mcpgateway/routers/log\_search.py                                              |      327 |       32 |      104 |       29 |     84% |74, 82->77, 98->100, 127-136, 139-141, 144->147, 153, 155, 169-174, 178->exit, 379, 395, 470->490, 473->490, 482->490, 539-541, 580->582, 582->584, 584->586, 586->588, 588->591, 591->594, 615-617, 658->660, 660->662, 662->664, 664->666, 666->668, 668->671, 671->674, 696-698, 732->746, 780-782 |
| mcpgateway/routers/metrics\_maintenance.py                                     |       93 |        0 |       10 |        0 |    100% |           |
| mcpgateway/routers/oauth\_router.py                                            |      236 |        0 |       66 |        4 |     99% |127->131, 198->205, 369->377, 585->588 |
| mcpgateway/routers/observability.py                                            |      148 |        7 |       32 |        4 |     94% |52-53, 564, 568, 622->exit, 648-649, 821 |
| mcpgateway/routers/rbac.py                                                     |      212 |       34 |        8 |        1 |     84% |61, 63-70, 121-123, 195-197, 201-203, 245-247, 285-287, 329-331, 367-370, 422-424 |
| mcpgateway/routers/reverse\_proxy.py                                           |      203 |       11 |       48 |        2 |     94% |211, 484-504 |
| mcpgateway/routers/server\_well\_known.py                                      |       39 |        0 |       10 |        0 |    100% |           |
| mcpgateway/routers/sso.py                                                      |      247 |        5 |       56 |        3 |     97% |187->191, 191->208, 341-346, 616-618 |
| mcpgateway/routers/teams.py                                                    |      411 |        0 |       84 |        0 |    100% |           |
| mcpgateway/routers/tokens.py                                                   |      180 |        5 |       44 |        5 |     96% |74, 98, 351, 633, 638 |
| mcpgateway/routers/toolops\_router.py                                          |       50 |        2 |        0 |        0 |     96% |   138-139 |
| mcpgateway/routers/well\_known.py                                              |      108 |        1 |       50 |        2 |     98% |184->187, 188 |
| mcpgateway/schemas.py                                                          |     2747 |        2 |      624 |       23 |     99% |576->580, 841->845, 1064->1073, 1153->1155, 1155->1157, 1262->1266, 3254->3273, 3258->3273, 3266->3265, 3269->3272, 3382->3392, 3888, 4553->4563, 4999->5018, 5003->5018, 5005->5018, 5011->5010, 5014->5017, 5123->5129, 5714->5718, 5809->5815, 5811->5815, 6888 |
| mcpgateway/scripts/validate\_env.py                                            |       68 |        6 |       36 |        2 |     88% |144, 243-249 |
| mcpgateway/services/a2a\_service.py                                            |      618 |       21 |      242 |       29 |     93% |287->289, 355->361, 358->361, 409->422, 414, 648, 786, 994->997, 1013, 1070->1074, 1074->1083, 1091, 1093->1125, 1102-1105, 1111-1122, 1125->1130, 1218->1221, 1279->1282, 1399->1398, 1403-1404, 1405->1409, 1415-1416, 1417->1424, 1560->1566, 1585->1591, 1618->1621, 1658->1660, 1705->1713, 1707->1711 |
| mcpgateway/services/argon2\_service.py                                         |       91 |        0 |       20 |        2 |     98% |253->247, 257->260 |
| mcpgateway/services/audit\_trail\_service.py                                   |      124 |       14 |       48 |       16 |     81% |134->138, 190->192, 215, 222, 264->273, 275, 276->280, 282, 284, 371-375, 406->410, 413->415, 416, 418, 420, 422, 424 |
| mcpgateway/services/cancellation\_service.py                                   |      150 |       17 |       34 |        7 |     87% |59, 69-70, 78-79, 93, 113, 132->105, 140-141, 144->exit, 149-152, 167, 169, 177->184, 180, 272 |
| mcpgateway/services/catalog\_service.py                                        |      265 |       13 |      106 |       11 |     94% |67->73, 78-85, 102-103, 138->166, 199->203, 245->244, 368-370, 397->400, 426->432, 438->441, 488->487, 521-523, 554 |
| mcpgateway/services/completion\_service.py                                     |       71 |        2 |       26 |        1 |     97% |  123, 127 |
| mcpgateway/services/dcr\_service.py                                            |      158 |       21 |       44 |        9 |     85% |51, 91->96, 115, 129, 139, 213, 228, 314, 317, 344-347, 363-364, 367-368, 383-387 |
| mcpgateway/services/elicitation\_service.py                                    |      133 |        4 |       44 |        7 |     94% |87->exit, 93->101, 103->102, 227, 231-232, 241->239, 243->239, 249->exit, 286 |
| mcpgateway/services/email\_auth\_service.py                                    |      463 |       67 |      136 |       11 |     84% |252, 390-391, 414, 528, 552-553, 572-575, 579-582, 626-627, 741, 750->763, 763->765, 769, 792-793, 804, 841-935, 966->974, 1065-1066, 1074->1078, 1250-1251 |
| mcpgateway/services/encryption\_service.py                                     |       66 |        0 |        8 |        0 |    100% |           |
| mcpgateway/services/event\_service.py                                          |       99 |       11 |       22 |        3 |     88% |215, 233-235, 251-252, 254-255, 261-262, 264-265, 269->exit, 297->exit |
| mcpgateway/services/export\_service.py                                         |      340 |       35 |      136 |       27 |     84% |170, 191, 212, 233, 254, 349->352, 352->355, 368->372, 439->452, 442->452, 444->452, 498->508, 500->508, 576->586, 650->649, 760->749, 764->768, 789, 797-825, 842, 849-870, 888, 896-910, 927, 935-951, 968, 975-985 |
| mcpgateway/services/gateway\_service.py                                        |     2210 |      184 |      910 |      119 |     89% |77-79, 514->exit, 565->570, 629->620, 647->620, 654->620, 739->750, 746->750, 760->764, 793->823, 911->908, 916-919, 998->995, 1003-1005, 1581-1585, 1597, 1650, 1715, 1798->1801, 1834-1840, 1859-1862, 1870->1892, 1883, 1953-1954, 1958, 1964, 2020->2038, 2026->2034, 2029->2034, 2034->2038, 2044-2050, 2076-2078, 2092->2094, 2095, 2097, 2117-2122, 2128-2132, 2156, 2158, 2171-2174, 2176-2179, 2479->2483, 2504->2503, 2528->2530, 2531, 2533, 2553-2558, 2564-2568, 2592, 2594, 2607-2610, 2612-2615, 2883, 3053, 3066->3108, 3117->3124, 3125-3127, 3131, 3136-3137, 3189->3191, 3223-3225, 3252->3279, 3262-3267, 3276, 3281, 3299->3306, 3302-3303, 3364-3367, 3516->3515, 3520-3521, 3522->3526, 3543-3547, 3549, 3568, 3605->3608, 3616->3619, 3623->3626, 3634->3637, 3655->3698, 3659-3695, 3707->3714, 3710-3711, 3718->3736, 3723, 3727->3730, 3751-3752, 3842->3839, 3978->3988, 4065->4067, 4068, 4103, 4138-4147, 4153->4158, 4155-4156, 4168-4170, 4180->4133, 4184-4185, 4188-4189, 4450, 4484->4486, 4486->4456, 4537, 4556->4565, 4565->4543, 4613, 4632->4639, 4639->4619, 4814->4813, 4818-4819, 4820->4824, 4866-4868, 4905->4917, 4908-4914, 4918->4929, 4921-4926, 4982->4984, 5230->5282, 5240->5242, 5268->5272, 5272->5275, 5278-5279, 5284->5308, 5291->5293, 5392->5446, 5404->5406, 5432->5436, 5436->5439, 5442-5443, 5447->5473, 5521, 5549->5553, 5554->5608, 5563->5566, 5566->5568, 5583-5584, 5594->5598, 5598->5601, 5604-5605, 5609->5625, 5619, 5622-5623 |
| mcpgateway/services/grpc\_service.py                                           |      229 |        8 |       80 |        7 |     95% |26-31, 214->217, 257->261, 305, 438-439, 465->464, 486->485, 494->493, 600->604 |
| mcpgateway/services/http\_client\_service.py                                   |       79 |        1 |       18 |        3 |     96% |55, 93->95, 95->97 |
| mcpgateway/services/import\_service.py                                         |      800 |        0 |      336 |       38 |     97% |296->exit, 634->exit, 701->exit, 763->exit, 825->exit, 874->exit, 923->exit, 1216->1257, 1230->1257, 1236->1257, 1243->1257, 1245->1257, 1285->1321, 1298->1321, 1303->1321, 1309->1321, 1311->1321, 1391->1393, 1415->1422, 1444->1451, 1526->1525, 1569->1573, 1573->1577, 1652->1651, 1655->1653, 1659->1646, 1686->1682, 1709->1723, 1716->1714, 1719->1723, 1723->1741, 1730->1728, 1733->1741, 1783->1786, 1786->1791, 1791->1795, 1795->1798, 1840->1835 |
| mcpgateway/services/llm\_provider\_service.py                                  |      276 |        0 |      100 |       15 |     96% |92->exit, 98->exit, 284->286, 507->509, 509->511, 511->513, 513->515, 515->517, 517->519, 519->521, 521->523, 523->525, 525->527, 527->529, 529->532 |
| mcpgateway/services/llm\_proxy\_service.py                                     |      280 |        0 |      140 |        0 |    100% |           |
| mcpgateway/services/log\_aggregator.py                                         |      355 |       14 |      136 |       23 |     92% |64, 66, 71->75, 78, 83, 118->120, 124->126, 256->223, 374->335, 383->385, 405, 408->412, 434->431, 437->439, 442->444, 466->470, 483->485, 488->490, 549->525, 566-569, 596->600, 612->614, 616->618, 620-623, 871 |
| mcpgateway/services/log\_storage\_service.py                                   |      154 |        1 |       44 |        5 |     97% |216->218, 245->254, 248->254, 257->exit, 346 |
| mcpgateway/services/logging\_service.py                                        |      238 |        8 |       56 |        3 |     96% |124->exit, 131-133, 158->178, 261-263, 463-465, 472-473, 677->682 |
| mcpgateway/services/mcp\_client\_chat\_service.py                              |      848 |        1 |      300 |       33 |     97% |665->668, 806->818, 905->921, 914->916, 997->1025, 1017->1020, 1116->1141, 1127->1136, 1233->1269, 1254->1264, 1365->1401, 1375->1377, 1377->1379, 1388->1397, 1559, 1660->1663, 2094->2088, 2192->2197, 2194->2197, 2239->2243, 2560->2554, 2626->2622, 2628->2622, 2630->2622, 2635->2639, 2762->2765, 2857->2747, 2863->2747, 2865->2747, 2867->2747, 2887->2889, 2899->2907, 3017->3021 |
| mcpgateway/services/mcp\_session\_pool.py                                      |      842 |        0 |      234 |        0 |    100% |           |
| mcpgateway/services/metrics.py                                                 |       50 |        0 |       14 |        1 |     98% |  121->130 |
| mcpgateway/services/metrics\_buffer\_service.py                                |      256 |       20 |       48 |       11 |     90% |147->exit, 160->168, 293-303, 364-375, 385->exit, 394, 397-399, 404-407, 426, 473->489, 489->505, 506, 522, 538, 737-738 |
| mcpgateway/services/metrics\_cleanup\_service.py                               |      185 |       31 |       40 |        9 |     80% |198->exit, 211->218, 231->exit, 240, 243-251, 256-259, 285, 302->321, 308, 368-379, 384-387, 392, 431-441 |
| mcpgateway/services/metrics\_query\_service.py                                 |      172 |       18 |       42 |       10 |     86% |195->202, 236, 308, 339, 365, 457, 563-580, 586, 589, 597-615 |
| mcpgateway/services/metrics\_rollup\_service.py                                |      345 |       22 |       86 |       15 |     90% |188->190, 217->exit, 230->237, 269, 275-276, 284, 290, 307-310, 479->518, 512->518, 514->518, 596->601, 640, 683, 688->694, 706-714, 730-732, 928 |
| mcpgateway/services/notification\_service.py                                   |      187 |        8 |       38 |        4 |     95% |59, 215, 481-487, 520->540, 529, 537-538 |
| mcpgateway/services/oauth\_manager.py                                          |      583 |        0 |      218 |        0 |    100% |           |
| mcpgateway/services/observability\_service.py                                  |      340 |       10 |      172 |       51 |     87% |249->253, 254->257, 317->320, 486, 676->679, 684->688, 688->692, 694->710, 837->841, 939->955, 1149->1151, 1151->1155, 1155->1157, 1157->1161, 1161->1163, 1163->1165, 1165->1169, 1169->1171, 1171->1175, 1175->1177, 1177->1181, 1181->1183, 1183->1187, 1187->1191, 1191->1198, 1198->1206, 1202->1206, 1206->1214, 1215, 1217, 1220-1221, 1323->1325, 1325->1329, 1329->1331, 1331->1335, 1335->1337, 1337->1341, 1341->1345, 1345->1347, 1347->1351, 1351->1353, 1353->1355, 1355->1359, 1359->1361, 1361->1365, 1365->1367, 1367->1371, 1371->1376, 1376->1381, 1382, 1384, 1387-1388, 1411 |
| mcpgateway/services/performance\_service.py                                    |      344 |       35 |      104 |       23 |     86% |60->65, 74-76, 84-86, 94-96, 162, 205-206, 264-265, 269-271, 293-294, 300-301, 351-352, 361-362, 388->387, 395, 399, 402->387, 405->385, 412->409, 415->385, 426->436, 429, 455->463, 483, 500->508, 504-506, 568, 570-571, 604->607, 645, 709->711, 711->713, 713->715, 715->699 |
| mcpgateway/services/performance\_tracker.py                                    |      124 |       15 |       38 |        9 |     84% |86->exit, 117-119, 134-146, 174, 260-261, 278, 282, 301->304, 335, 339, 349 |
| mcpgateway/services/permission\_service.py                                     |      168 |        1 |       68 |        2 |     99% |353->358, 456 |
| mcpgateway/services/personal\_team\_service.py                                 |       71 |        0 |        8 |        0 |    100% |           |
| mcpgateway/services/plugin\_service.py                                         |      107 |        3 |       54 |       10 |     92% |34->39, 105->109, 113, 119->144, 121->120, 138->142, 182->185, 189->208, 192, 231 |
| mcpgateway/services/prompt\_service.py                                         |      860 |       71 |      316 |       42 |     89% |208-209, 479->481, 530, 534-535, 780->782, 811->813, 813->815, 852->855, 857->764, 886-887, 1057, 1067-1073, 1087, 1209, 1295->1300, 1304-1309, 1421->1434, 1426-1428, 1500-1517, 1540-1554, 1557-1568, 1592, 1599-1606, 1626-1627, 1631-1639, 1680-1683, 1707-1708, 1712-1722, 1803->1813, 1805->1813, 1809->1813, 1825-1827, 1848->1850, 1873, 2059->2103, 2066->2070, 2172, 2356->exit, 2464->2471, 2475, 2485->2492, 2623->2630, 2626, 2636->2639 |
| mcpgateway/services/resource\_service.py                                       |     1154 |      142 |      440 |       55 |     85% |81-82, 342->344, 449, 747->689, 823-828, 904->920, 910-914, 1000-1001, 1024, 1032-1041, 1057, 1119-1120, 1190->1193, 1212, 1305-1329, 1337->1341, 1348-1349, 1531->1534, 1616-1617, 1674-1684, 1698-1731, 1736, 1782, 1788-1793, 1796-1806, 1864, 1870-1875, 1878-1888, 1899-1900, 1920-1923, 1937-1938, 2120, 2125, 2129-2134, 2161-2162, 2174, 2198->2206, 2200->2202, 2208, 2215, 2218-2219, 2223, 2232, 2239-2246, 2250-2253, 2296->2321, 2307->2321, 2311, 2316, 2346-2347, 2430->2435, 2659->2670, 2666->2670, 2720, 3075->3082, 3180->exit, 3227, 3236, 3245-3246, 3251, 3465, 3468, 3509->3516, 3512, 3532->3535 |
| mcpgateway/services/role\_service.py                                           |      174 |        1 |       78 |        2 |     99% |428, 447->460 |
| mcpgateway/services/root\_service.py                                           |       96 |        2 |       20 |        1 |     97% |81-82, 275->279 |
| mcpgateway/services/security\_logger.py                                        |      144 |        0 |       40 |        1 |     99% |  596->598 |
| mcpgateway/services/server\_service.py                                         |      605 |       28 |      258 |       22 |     94% |178, 182-183, 553, 559, 572, 577, 589, 598-602, 773-774, 807->809, 812, 840, 895, 963, 1161->1170, 1167, 1183->1187, 1191, 1206, 1216, 1235, 1302, 1328, 1484, 1494->1536, 1567 |
| mcpgateway/services/sso\_service.py                                            |      403 |        2 |      208 |       18 |     97% |268->267, 558->587, 589->596, 592->591, 682->685, 717->721, 723->726, 780->796, 800->809, 809->893, 821->825, 835->856, 877, 879->885, 882, 887->893, 1027->1014, 1036->1040 |
| mcpgateway/services/structured\_logger.py                                      |      161 |        1 |       34 |        3 |     98% |35, 135->141, 144->151, 311->315 |
| mcpgateway/services/support\_bundle\_service.py                                |      117 |       15 |       28 |        3 |     85% |257-258, 305->307, 307->310, 336-354 |
| mcpgateway/services/system\_stats\_service.py                                  |      100 |        0 |        4 |        0 |    100% |           |
| mcpgateway/services/tag\_service.py                                            |      143 |        9 |       72 |        5 |     92% |157, 208-211, 317, 416, 423-426 |
| mcpgateway/services/team\_invitation\_service.py                               |      190 |        0 |       56 |        0 |    100% |           |
| mcpgateway/services/team\_management\_service.py                               |      679 |        0 |      182 |        0 |    100% |           |
| mcpgateway/services/token\_catalog\_service.py                                 |      253 |       28 |       86 |       10 |     87% |334, 338, 342, 346, 354-359, 561, 566->569, 709-710, 735-756, 850->854, 874, 965->964 |
| mcpgateway/services/token\_storage\_service.py                                 |      183 |        2 |       56 |        2 |     98% |  232, 261 |
| mcpgateway/services/tool\_service.py                                           |     1611 |      155 |      626 |       45 |     89% |972-973, 1461->1437, 1607->1611, 1810, 1824->1826, 1847, 1912-1913, 2002, 2012->2014, 2014->2016, 2110->2113, 2140, 2679->2683, 2737->2736, 2755->2762, 2758-2760, 2779, 2818->2821, 2821->2830, 2923->2925, 2936->2940, 2990-2991, 2999-3005, 3054-3074, 3080-3082, 3098-3102, 3115, 3136-3155, 3210-3215, 3219-3227, 3250-3312, 3355-3360, 3365-3374, 3378, 3397-3459, 3466->3468, 3468->3470, 3477->3484, 3481->3484, 3498, 3508-3522, 3547-3548, 3554, 3558->3557, 3562-3563, 3564->3568, 3589-3590, 3594-3600, 3650, 3656->3659, 3670-3671, 3711-3712, 4371, 4463, 4465, 4626-4628, 4655->4654, 4659-4660, 4661->4667 |
| mcpgateway/toolops/toolops\_altk\_service.py                                   |      135 |       18 |       32 |       11 |     83% |32-37, 66, 117, 120, 123, 126, 157->188, 169->188, 170->188, 173->188, 177-179, 249-250, 255->268, 265-266 |
| mcpgateway/toolops/utils/db\_util.py                                           |       34 |        0 |        4 |        1 |     97% |  78->exit |
| mcpgateway/toolops/utils/format\_conversion.py                                 |       23 |        0 |        6 |        0 |    100% |           |
| mcpgateway/toolops/utils/llm\_util.py                                          |       85 |       10 |       14 |        2 |     88% |176-182, 203-207 |
| mcpgateway/tools/builder/cli.py                                                |      114 |        1 |       14 |        2 |     98% |105, 151->exit |
| mcpgateway/tools/builder/factory.py                                            |       31 |        1 |        8 |        2 |     92% |119->122, 134 |
| mcpgateway/tools/builder/pipeline.py                                           |       39 |        2 |        6 |        2 |     91% |  184, 205 |
| mcpgateway/tools/builder/schema.py                                             |       85 |        0 |        6 |        0 |    100% |           |
| mcpgateway/tools/cli.py                                                        |        8 |        1 |        0 |        0 |     88% |        53 |
| mcpgateway/translate.py                                                        |      806 |        4 |      292 |        0 |     99% | 1542-1545 |
| mcpgateway/translate\_grpc.py                                                  |      224 |       13 |       68 |        4 |     94% |27-36, 133->132, 166->165, 175-177, 181->180, 430, 442 |
| mcpgateway/translate\_header\_utils.py                                         |       76 |        6 |       26 |        4 |     90% |65, 159, 165, 341-343 |
| mcpgateway/transports/base.py                                                  |       13 |        0 |        0 |        0 |    100% |           |
| mcpgateway/transports/redis\_event\_store.py                                   |       78 |       13 |       18 |        7 |     79% |26, 179, 219-220, 228-229, 234, 242->250, 245-246, 248, 255, 258-259 |
| mcpgateway/transports/sse\_transport.py                                        |      252 |       26 |       68 |       12 |     87% |103->105, 124, 167-169, 256->260, 262->exit, 594->600, 735, 741->750, 745->750, 753->816, 771, 780->753, 783-787, 806-814, 820->exit, 828-836 |
| mcpgateway/transports/stdio\_transport.py                                      |       56 |        0 |        8 |        0 |    100% |           |
| mcpgateway/transports/streamablehttp\_transport.py                             |      745 |       12 |      256 |       25 |     96% |298->300, 518->525, 564->573, 568->573, 577->625, 593, 607, 609, 612-613, 906->912, 1030->1036, 1209->1213, 1374-1375, 1400->1396, 1402->1396, 1431, 1445->1448, 1487->1483, 1489->1483, 1529->1613, 1540->1536, 1542-1543, 1572, 1636->1638, 1638->1640, 1640->1635, 1673, 1867->1913 |
| mcpgateway/transports/websocket\_transport.py                                  |       81 |        3 |       18 |        2 |     95% |113->116, 143-145, 149 |
| mcpgateway/utils/analyze\_query\_log.py                                        |       97 |        0 |       36 |        0 |    100% |           |
| mcpgateway/utils/base\_models.py                                               |        8 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/correlation\_id.py                                            |       38 |        0 |       14 |        0 |    100% |           |
| mcpgateway/utils/create\_jwt\_token.py                                         |       84 |        0 |       26 |        0 |    100% |           |
| mcpgateway/utils/create\_slug.py                                               |       13 |        0 |        2 |        0 |    100% |           |
| mcpgateway/utils/db\_isready.py                                                |       93 |        0 |       20 |        0 |    100% |           |
| mcpgateway/utils/display\_name.py                                              |        9 |        0 |        4 |        0 |    100% |           |
| mcpgateway/utils/error\_formatter.py                                           |       54 |        0 |       32 |        0 |    100% |           |
| mcpgateway/utils/generate\_keys.py                                             |       31 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/jwt\_config\_helper.py                                        |       67 |        0 |       24 |        0 |    100% |           |
| mcpgateway/utils/keycloak\_discovery.py                                        |       46 |        0 |        4 |        0 |    100% |           |
| mcpgateway/utils/metadata\_capture.py                                          |       55 |        0 |       24 |        0 |    100% |           |
| mcpgateway/utils/metrics\_common.py                                            |        4 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/orjson\_response.py                                           |        7 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/pagination.py                                                 |      174 |        0 |       70 |        0 |    100% |           |
| mcpgateway/utils/passthrough\_headers.py                                       |      158 |        0 |       72 |        0 |    100% |           |
| mcpgateway/utils/psycopg3\_optimizations.py                                    |      100 |        0 |       34 |        0 |    100% |           |
| mcpgateway/utils/redis\_client.py                                              |       79 |        0 |       18 |        0 |    100% |           |
| mcpgateway/utils/redis\_isready.py                                             |       52 |        0 |       10 |        0 |    100% |           |
| mcpgateway/utils/retry\_manager.py                                             |      124 |        0 |       40 |        0 |    100% |           |
| mcpgateway/utils/security\_cookies.py                                          |       46 |        5 |        8 |        2 |     87% |110-111, 114-115, 118 |
| mcpgateway/utils/services\_auth.py                                             |       56 |        0 |       12 |        0 |    100% |           |
| mcpgateway/utils/sqlalchemy\_modifier.py                                       |      120 |        0 |       50 |        0 |    100% |           |
| mcpgateway/utils/ssl\_context\_cache.py                                        |       20 |        0 |        8 |        0 |    100% |           |
| mcpgateway/utils/ssl\_key\_manager.py                                          |       46 |        0 |        6 |        0 |    100% |           |
| mcpgateway/utils/sso\_bootstrap.py                                             |       68 |        0 |       28 |        0 |    100% |           |
| mcpgateway/utils/token\_scoping.py                                             |       30 |        0 |       10 |        0 |    100% |           |
| mcpgateway/utils/url\_auth.py                                                  |       45 |        0 |       16 |        0 |    100% |           |
| mcpgateway/utils/validate\_signature.py                                        |       71 |        0 |       20 |        0 |    100% |           |
| mcpgateway/utils/verify\_credentials.py                                        |      186 |        0 |       96 |        0 |    100% |           |
| mcpgateway/validation/jsonrpc.py                                               |       58 |        0 |       34 |        0 |    100% |           |
| mcpgateway/validation/tags.py                                                  |       72 |        3 |       38 |        3 |     95% |167, 257, 265 |
| mcpgateway/version.py                                                          |      137 |       16 |       24 |        3 |     87% |84-85, 89-96, 835-840, 845-853 |
| mcpgateway/wrapper.py                                                          |      307 |        0 |      134 |        0 |    100% |           |
| **TOTAL**                                                                      | **51431** | **1792** | **15600** | **1308** | **95%** |           |
