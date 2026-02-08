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
| tests/unit/mcpgateway/middleware/test_rbac.py                                                   |     51 |       9 |       60 |
| tests/unit/mcpgateway/plugins/plugins/altk_json_processor/test_json_processor.py                |      0 |       1 |        1 |
| tests/unit/mcpgateway/plugins/plugins/sparc_static_validator/test_sparc_static_validator.py     |      4 |      32 |       36 |
| tests/unit/mcpgateway/plugins/test_pii_filter_rust.py                                           |      1 |      44 |       45 |
| tests/unit/mcpgateway/plugins/tools/test_cli.py                                                 |      8 |       1 |        9 |
| tests/unit/mcpgateway/routers/test_reverse_proxy.py                                             |     42 |       1 |       43 |
| tests/unit/mcpgateway/routers/test_teams.py                                                     |     39 |       5 |       44 |
| tests/unit/mcpgateway/services/test_email_auth_basic.py                                         |     88 |       3 |       91 |
| tests/unit/mcpgateway/services/test_event_service.py                                            |     22 |       5 |       27 |
| tests/unit/mcpgateway/services/test_gateway_service.py                                          |    107 |       1 |      108 |
| tests/unit/mcpgateway/services/test_gateway_service_extended.py                                 |     37 |       1 |       38 |
| tests/unit/mcpgateway/services/test_mcp_client_chat_service_extended.py                         |     60 |       1 |       61 |
| tests/unit/mcpgateway/services/test_row_level_locking.py                                        |     16 |       2 |       18 |
| tests/unit/mcpgateway/services/test_team_invitation_service.py                                  |     37 |       4 |       41 |
| tests/unit/mcpgateway/test_observability.py                                                     |     31 |       1 |       32 |
| tests/unit/mcpgateway/test_postgresql_schema_config.py                                          |     14 |       2 |       16 |
| tests/unit/mcpgateway/test_ui_version.py                                                        |      0 |       1 |        1 |
| tests/unit/mcpgateway/tools/builder/test_dagger_deploy.py                                       |      0 |      20 |       20 |
| tests/unit/mcpgateway/validation/test_validators_advanced.py                                    |     42 |       3 |       45 |
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
| tests/unit/mcpgateway/middleware/test_request_context.py                                        |      1 |       0 |        1 |
| tests/unit/mcpgateway/middleware/test_request_logging_middleware.py                             |     27 |       0 |       27 |
| tests/unit/mcpgateway/middleware/test_security_headers_middleware.py                            |     16 |       0 |       16 |
| tests/unit/mcpgateway/middleware/test_token_scoping.py                                          |     35 |       0 |       35 |
| tests/unit/mcpgateway/middleware/test_token_scoping_extra.py                                    |      9 |       0 |        9 |
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
| tests/unit/mcpgateway/plugins/framework/external/mcp/server/test_server.py                      |     32 |       0 |       32 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_certificate_validation.py      |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_config.py                      |     16 |       0 |       16 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_tls_utils.py                          |     27 |       0 |       27 |
| tests/unit/mcpgateway/plugins/framework/external/test_proto_convert.py                          |     46 |       0 |       46 |
| tests/unit/mcpgateway/plugins/framework/external/mcp/test_client_stdio.py                       |      7 |       0 |        7 |
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
| tests/unit/mcpgateway/plugins/framework/test_errors.py                                          |      3 |       0 |        3 |
| tests/unit/mcpgateway/plugins/framework/test_context.py                                         |      2 |       0 |        2 |
| tests/unit/mcpgateway/plugins/framework/test_manager.py                                         |     12 |       0 |       12 |
| tests/unit/mcpgateway/plugins/framework/test_manager_extended.py                                |     16 |       0 |       16 |
| tests/unit/mcpgateway/plugins/framework/test_memory.py                                          |     80 |       0 |       80 |
| tests/unit/mcpgateway/plugins/framework/test_models_tls.py                                      |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_base.py                                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/framework/test_plugin_models.py                                   |     25 |       0 |       25 |
| tests/unit/mcpgateway/plugins/framework/test_registry.py                                        |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/framework/test_resource_hooks.py                                  |     13 |       0 |       13 |
| tests/unit/mcpgateway/plugins/framework/test_utils.py                                           |     11 |       0 |       11 |
| tests/unit/mcpgateway/plugins/plugins/argument_normalizer/test_argument_normalizer.py           |      4 |       0 |        4 |
| tests/unit/mcpgateway/plugins/plugins/cached_tool_result/test_cached_tool_result.py             |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/code_safety_linter/test_code_safety_linter.py             |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation.py             |     17 |       0 |       17 |
| tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/plugins/external_clamav/test_clamav_remote.py                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/plugins/plugins/file_type_allowlist/test_file_type_allowlist.py           |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/html_to_markdown/test_html_to_markdown.py                 |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/json_repair/test_json_repair.py                           |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/markdown_cleaner/test_markdown_cleaner.py                 |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/output_length_guard/test_output_length_guard.py           |      5 |       0 |        5 |
| tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py                             |     18 |       0 |       18 |
| tests/unit/mcpgateway/plugins/plugins/rate_limiter/test_rate_limiter.py                         |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/resource_filter/test_resource_filter.py                   |     15 |       0 |       15 |
| tests/unit/mcpgateway/plugins/plugins/response_cache_by_prompt/test_response_cache_by_prompt.py |     19 |       0 |       19 |
| tests/unit/mcpgateway/plugins/plugins/schema_guard/test_schema_guard.py                         |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/test_init_hooks_plugins.py                                |    107 |       0 |      107 |
| tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin.py                                |      9 |       0 |        9 |
| tests/unit/mcpgateway/plugins/plugins/url_reputation/test_url_reputation.py                     |      1 |       0 |        1 |
| tests/unit/mcpgateway/plugins/plugins/vault/test_vault_plugin_smoke.py                          |      3 |       0 |        3 |
| tests/unit/mcpgateway/plugins/plugins/virus_total_checker/test_virus_total_checker.py           |      8 |       0 |        8 |
| tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_integration.py          |      4 |       0 |        4 |
| tests/unit/mcpgateway/plugins/plugins/webhook_notification/test_webhook_notification.py         |     14 |       0 |       14 |
| tests/unit/mcpgateway/routers/test_auth.py                                                      |     15 |       0 |       15 |
| tests/unit/mcpgateway/routers/test_cancellation_router.py                                       |     13 |       0 |       13 |
| tests/unit/mcpgateway/routers/test_email_auth_helpers.py                                        |      8 |       0 |        8 |
| tests/unit/mcpgateway/routers/test_email_auth_router.py                                         |     62 |       0 |       62 |
| tests/unit/mcpgateway/routers/test_llm_admin_router.py                                          |     18 |       0 |       18 |
| tests/unit/mcpgateway/routers/test_llm_config_router.py                                         |     32 |       0 |       32 |
| tests/unit/mcpgateway/routers/test_llm_proxy_router.py                                          |      4 |       0 |        4 |
| tests/unit/mcpgateway/routers/test_llmchat_router.py                                            |     37 |       0 |       37 |
| tests/unit/mcpgateway/routers/test_log_search.py                                                |     12 |       0 |       12 |
| tests/unit/mcpgateway/routers/test_log_search_helpers.py                                        |      4 |       0 |        4 |
| tests/unit/mcpgateway/routers/test_metrics_maintenance.py                                       |     10 |       0 |       10 |
| tests/unit/mcpgateway/routers/test_oauth_router.py                                              |     59 |       0 |       59 |
| tests/unit/mcpgateway/routers/test_observability_sql.py                                         |     19 |       0 |       19 |
| tests/unit/mcpgateway/routers/test_rbac_router.py                                               |     18 |       0 |       18 |
| tests/unit/mcpgateway/routers/test_sso_router.py                                                |     33 |       0 |       33 |
| tests/unit/mcpgateway/routers/test_teams_v2.py                                                  |     10 |       0 |       10 |
| tests/unit/mcpgateway/routers/test_tokens.py                                                    |     38 |       0 |       38 |
| tests/unit/mcpgateway/services/test_a2a_query_param_auth.py                                     |      9 |       0 |        9 |
| tests/unit/mcpgateway/services/test_a2a_service.py                                              |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_argon2_service.py                                           |     61 |       0 |       61 |
| tests/unit/mcpgateway/services/test_async_crypto_wrappers.py                                    |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_audit_trail_service.py                                      |      6 |       0 |        6 |
| tests/unit/mcpgateway/services/test_authorization_access.py                                     |     34 |       0 |       34 |
| tests/unit/mcpgateway/services/test_cancellation_service.py                                     |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_catalog_service.py                                          |     22 |       0 |       22 |
| tests/unit/mcpgateway/services/test_completion_service.py                                       |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_correlation_id_json_formatter.py                            |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_dcr_service.py                                              |     30 |       0 |       30 |
| tests/unit/mcpgateway/services/test_elicitation_service.py                                      |     10 |       0 |       10 |
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
| tests/unit/mcpgateway/services/test_import_service.py                                           |    100 |       0 |      100 |
| tests/unit/mcpgateway/services/test_llm_provider_service.py                                     |     36 |       0 |       36 |
| tests/unit/mcpgateway/services/test_llm_proxy_service.py                                        |     61 |       0 |       61 |
| tests/unit/mcpgateway/services/test_log_aggregator.py                                           |     52 |       0 |       52 |
| tests/unit/mcpgateway/services/test_log_aggregator_helpers.py                                   |      2 |       0 |        2 |
| tests/unit/mcpgateway/services/test_log_storage_service.py                                      |     28 |       0 |       28 |
| tests/unit/mcpgateway/services/test_logging_service.py                                          |      7 |       0 |        7 |
| tests/unit/mcpgateway/services/test_logging_service_comprehensive.py                            |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_mcp_chat_history_extra.py                                   |      3 |       0 |        3 |
| tests/unit/mcpgateway/services/test_mcp_client_chat_service.py                                  |     27 |       0 |       27 |
| tests/unit/mcpgateway/services/test_mcp_session_pool.py                                         |     69 |       0 |       69 |
| tests/unit/mcpgateway/services/test_metrics_buffer_service.py                                   |     33 |       0 |       33 |
| tests/unit/mcpgateway/services/test_metrics_cleanup_service.py                                  |     17 |       0 |       17 |
| tests/unit/mcpgateway/services/test_metrics_query_service.py                                    |     39 |       0 |       39 |
| tests/unit/mcpgateway/services/test_metrics_rollup_service.py                                   |     34 |       0 |       34 |
| tests/unit/mcpgateway/services/test_notification_service.py                                     |     38 |       0 |       38 |
| tests/unit/mcpgateway/services/test_oauth_manager_pkce.py                                       |    115 |       0 |      115 |
| tests/unit/mcpgateway/services/test_observability_service.py                                    |     59 |       0 |       59 |
| tests/unit/mcpgateway/services/test_performance_service.py                                      |     44 |       0 |       44 |
| tests/unit/mcpgateway/services/test_performance_tracker.py                                      |     25 |       0 |       25 |
| tests/unit/mcpgateway/services/test_permission_fallback.py                                      |     15 |       0 |       15 |
| tests/unit/mcpgateway/services/test_permission_service_comprehensive.py                         |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_personal_team_service.py                                    |     27 |       0 |       27 |
| tests/unit/mcpgateway/services/test_plugin_service.py                                           |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_prompt_service.py                                           |     51 |       0 |       51 |
| tests/unit/mcpgateway/services/test_prompt_service_extended.py                                  |     24 |       0 |       24 |
| tests/unit/mcpgateway/services/test_resource_ownership.py                                       |     16 |       0 |       16 |
| tests/unit/mcpgateway/services/test_resource_service.py                                         |     95 |       0 |       95 |
| tests/unit/mcpgateway/services/test_resource_service_plugins.py                                 |     13 |       0 |       13 |
| tests/unit/mcpgateway/services/test_role_service.py                                             |     66 |       0 |       66 |
| tests/unit/mcpgateway/services/test_root_service.py                                             |     11 |       0 |       11 |
| tests/unit/mcpgateway/services/test_server_service.py                                           |     33 |       0 |       33 |
| tests/unit/mcpgateway/services/test_sso_admin_assignment.py                                     |      6 |       0 |        6 |
| tests/unit/mcpgateway/services/test_sso_approval_workflow.py                                    |      4 |       0 |        4 |
| tests/unit/mcpgateway/services/test_sso_entra_role_mapping.py                                   |     35 |       0 |       35 |
| tests/unit/mcpgateway/services/test_sso_user_normalization.py                                   |     25 |       0 |       25 |
| tests/unit/mcpgateway/services/test_support_bundle_service.py                                   |     15 |       0 |       15 |
| tests/unit/mcpgateway/services/test_system_stats_service.py                                     |     10 |       0 |       10 |
| tests/unit/mcpgateway/services/test_tag_service.py                                              |     26 |       0 |       26 |
| tests/unit/mcpgateway/services/test_team_management_service.py                                  |     89 |       0 |       89 |
| tests/unit/mcpgateway/services/test_token_catalog_service.py                                    |     75 |       0 |       75 |
| tests/unit/mcpgateway/services/test_tool_service.py                                             |    166 |       0 |      166 |
| tests/unit/mcpgateway/services/test_tool_service_helpers.py                                     |      3 |       0 |        3 |
| tests/unit/mcpgateway/test_admin.py                                                             |    262 |       0 |      262 |
| tests/unit/mcpgateway/test_admin_catalog_htmx.py                                                |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_error_handlers.py                                              |      9 |       0 |        9 |
| tests/unit/mcpgateway/test_admin_import_export.py                                               |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_metrics_helpers.py                                             |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_admin_module.py                                                      |     34 |       0 |       34 |
| tests/unit/mcpgateway/test_admin_observability_sql.py                                           |     27 |       0 |       27 |
| tests/unit/mcpgateway/test_auth.py                                                              |     76 |       0 |       76 |
| tests/unit/mcpgateway/test_auth_helpers.py                                                      |     13 |       0 |       13 |
| tests/unit/mcpgateway/test_bootstrap_db.py                                                      |     35 |       0 |       35 |
| tests/unit/mcpgateway/test_cli.py                                                               |      9 |       0 |        9 |
| tests/unit/mcpgateway/test_cli_config_schema.py                                                 |     14 |       0 |       14 |
| tests/unit/mcpgateway/test_cli_export_import_coverage.py                                        |     32 |       0 |       32 |
| tests/unit/mcpgateway/test_config.py                                                            |     16 |       0 |       16 |
| tests/unit/mcpgateway/test_coverage_push.py                                                     |     13 |       0 |       13 |
| tests/unit/mcpgateway/test_db.py                                                                |     78 |       0 |       78 |
| tests/unit/mcpgateway/test_db_isready.py                                                        |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_display_name_uuid_features.py                                        |     28 |       0 |       28 |
| tests/unit/mcpgateway/test_final_coverage_push.py                                               |     24 |       0 |       24 |
| tests/unit/mcpgateway/test_issue_840_a2a_agent.py                                               |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_llm_schemas.py                                                       |     17 |       0 |       17 |
| tests/unit/mcpgateway/test_main.py                                                              |    204 |       0 |      204 |
| tests/unit/mcpgateway/test_main_error_handlers.py                                               |     29 |       0 |       29 |
| tests/unit/mcpgateway/test_main_extended.py                                                     |     95 |       0 |       95 |
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
| tests/unit/mcpgateway/test_schemas_validators_extra.py                                          |     16 |       0 |       16 |
| tests/unit/mcpgateway/test_settings_fields.py                                                   |     32 |       0 |       32 |
| tests/unit/mcpgateway/test_simple_coverage_boost.py                                             |      7 |       0 |        7 |
| tests/unit/mcpgateway/test_toolops_altk_service.py                                              |     10 |       0 |       10 |
| tests/unit/mcpgateway/test_streamable_closedresource_filter.py                                  |      1 |       0 |        1 |
| tests/unit/mcpgateway/test_toolops_utils.py                                                     |     12 |       0 |       12 |
| tests/unit/mcpgateway/test_translate.py                                                         |     93 |       0 |       93 |
| tests/unit/mcpgateway/test_translate_grpc.py                                                    |     39 |       0 |       39 |
| tests/unit/mcpgateway/test_translate_grpc_helpers.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_translate_header_utils.py                                            |      4 |       0 |        4 |
| tests/unit/mcpgateway/test_translate_helpers.py                                                 |      5 |       0 |        5 |
| tests/unit/mcpgateway/test_translate_stdio_endpoint.py                                          |     21 |       0 |       21 |
| tests/unit/mcpgateway/test_version.py                                                           |     21 |       0 |       21 |
| tests/unit/mcpgateway/test_validate_env.py                                                      |      2 |       0 |        2 |
| tests/unit/mcpgateway/test_well_known.py                                                        |     35 |       0 |       35 |
| tests/unit/mcpgateway/test_wrapper.py                                                           |     21 |       0 |       21 |
| tests/unit/mcpgateway/tools/builder/test_cli.py                                                 |     37 |       0 |       37 |
| tests/unit/mcpgateway/tools/builder/test_common.py                                              |     38 |       0 |       38 |
| tests/unit/mcpgateway/tools/builder/test_python_deploy.py                                       |     15 |       0 |       15 |
| tests/unit/mcpgateway/tools/builder/test_schema.py                                              |     29 |       0 |       29 |
| tests/unit/mcpgateway/transports/test_redis_event_store.py                                      |     10 |       0 |       10 |
| tests/unit/mcpgateway/transports/test_sse_transport.py                                          |     23 |       0 |       23 |
| tests/unit/mcpgateway/transports/test_stdio_transport.py                                        |     11 |       0 |       11 |
| tests/unit/mcpgateway/transports/test_streamablehttp_transport.py                               |     76 |       0 |       76 |
| tests/unit/mcpgateway/transports/test_websocket_transport.py                                    |     15 |       0 |       15 |
| tests/unit/mcpgateway/utils/test_analyze_query_log.py                                           |      7 |       0 |        7 |
| tests/unit/mcpgateway/utils/test_correlation_id.py                                              |     18 |       0 |       18 |
| tests/unit/mcpgateway/utils/test_create_jwt_token.py                                            |     22 |       0 |       22 |
| tests/unit/mcpgateway/utils/test_error_formatter.py                                             |     19 |       0 |       19 |
| tests/unit/mcpgateway/utils/test_generate_keys.py                                               |      3 |       0 |        3 |
| tests/unit/mcpgateway/utils/test_jwt_config_helper.py                                           |     17 |       0 |       17 |
| tests/unit/mcpgateway/utils/test_keycloak_discovery.py                                          |      6 |       0 |        6 |
| tests/unit/mcpgateway/utils/test_metadata_capture.py                                            |     32 |       0 |       32 |
| tests/unit/mcpgateway/utils/test_metrics_common.py                                              |      2 |       0 |        2 |
| tests/unit/mcpgateway/utils/test_orjson_response.py                                             |     29 |       0 |       29 |
| tests/unit/mcpgateway/utils/test_pagination.py                                                  |     33 |       0 |       33 |
| tests/unit/mcpgateway/utils/test_passthrough_headers.py                                         |     20 |       0 |       20 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_fixed.py                                   |      9 |       0 |        9 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_security.py                                |     18 |       0 |       18 |
| tests/unit/mcpgateway/utils/test_passthrough_headers_source.py                                  |      8 |       0 |        8 |
| tests/unit/mcpgateway/utils/test_proxy_auth.py                                                  |     23 |       0 |       23 |
| tests/unit/mcpgateway/utils/test_psycopg3_optimizations.py                                      |     11 |       0 |       11 |
| tests/unit/mcpgateway/utils/test_redis_client.py                                                |     20 |       0 |       20 |
| tests/unit/mcpgateway/utils/test_redis_isready.py                                               |     11 |       0 |       11 |
| tests/unit/mcpgateway/utils/test_retry_manager.py                                               |     47 |       0 |       47 |
| tests/unit/mcpgateway/utils/test_services_auth.py                                               |      7 |       0 |        7 |
| tests/unit/mcpgateway/utils/test_sqlalchemy_modifier.py                                         |     28 |       0 |       28 |
| tests/unit/mcpgateway/utils/test_ssl_key_manager.py                                             |     10 |       0 |       10 |
| tests/unit/mcpgateway/utils/test_sso_bootstrap.py                                               |      7 |       0 |        7 |
| tests/unit/mcpgateway/utils/test_token_scoping_utils.py                                         |      6 |       0 |        6 |
| tests/unit/mcpgateway/utils/test_url_auth.py                                                    |     29 |       0 |       29 |
| tests/unit/mcpgateway/utils/test_validate_signature.py                                          |     14 |       0 |       14 |
| tests/unit/mcpgateway/utils/test_verify_credentials.py                                          |     39 |       0 |       39 |
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
| TOTAL                                                                                           |   7830 |     407 |     8237 |

## Coverage report

| Name                                                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| mcpgateway/admin.py                                                            |     5686 |     1441 |     1586 |      387 |     72% |161-176, 225->231, 640, 649, 656, 815, 818, 823, 873-874, 891->893, 905-911, 945->943, 989-997, 1081, 1084, 1321-1323, 1552->1558, 1574-1579, 1587, 1588->1592, 1616-1617, 1752-1758, 1763-1769, 1774-1780, 1786-1804, 1819-1821, 1860, 1927-1933, 1938-1944, 1949-1955, 1967->1970, 1970->1981, 2014, 2018, 2020, 2028-2029, 2076-2077, 2088, 2129-2134, 2140-2143, 2350-2351, 2362, 2366, 2420->2456, 2444-2449, 2461-2462, 2466-2467, 2572, 2579, 2601-2602, 2615-2616, 2623->2618, 2626->2618, 2639-2641, 2648-2650, 2665-2667, 2674-2676, 2718-2723, 2725, 2734-2736, 2765-2775, 2826->2866, 2913, 2966-2967, 2979->2981, 3011-3017, 3023->3034, 3032, 3062-3074, 3150, 3163, 3200-3207, 3267-3268, 3302-3307, 3333-3342, 3357-3375, 3552, 3614, 3615->3618, 3617, 3678, 3679->3682, 3681, 3759, 3778, 3781, 3791-3792, 3796, 3798->3801, 3836, 3870-3871, 3876-3877, 3884, 3886, 3888, 3890, 3962->3965, 3998-4000, 4097-4114, 4120, 4125-4133, 4187, 4286-4288, 4311, 4327, 4422-4424, 4445, 4454, 4503-4505, 4531, 4555-4556, 4560-4570, 4575, 4576->4594, 4579-4591, 4611-4623, 4645, 4669-4671, 4696, 4706, 4710->4715, 4728-4730, 4737, 4745, 4771, 4775, 4793->4769, 4796-4797, 4806-4808, 4824-4825, 4828-4829, 4835-4837, 4841->4843, 4843->4845, 4845->4847, 4847->4854, 4852, 4855, 4887-4889, 4912, 4920, 4926, 4935, 4938, 4963-4965, 4988, 4996, 5002, 5009, 5016-5019, 5040-5042, 5065, 5073, 5081, 5090->5094, 5096, 5108-5110, 5138, 5150, 5155, 5195-5197, 5220, 5242-5244, 5267, 5277, 5281, 5333-5335, 5358, 5367, 5372, 5385-5387, 5410, 5422-5439, 5470, 5476, 5478, 5493->5535, 5583, 5649, 5709->5703, 5712-5713, 5753-5767, 5805-5806, 5810, 5814, 5847-5849, 5877, 5888-5889, 5893, 5897, 5927-5929, 5955, 5962, 6008->6015, 6026-6027, 6037-6039, 6097->6103, 6103->6109, 6109->6115, 6115->6121, 6194-6196, 6218, 6243->6247, 6254-6256, 6270-6272, 6294, 6315-6317, 6339, 6368-6370, 6393, 6420-6422, 6469, 6486, 6497-6499, 6599->6614, 6606-6611, 6614->6620, 6658, 6687-6688, 6780->6793, 6784-6785, 6787-6788, 6793->6796, 6805-6806, 6810->6812, 6881->6886, 6888->6904, 6894-6899, 6978->6992, 6985-6990, 6992->6998, 7008-7009, 7110->7123, 7114-7115, 7117-7118, 7123->7129, 7141-7150, 7158, 7161->7165, 7184->7189, 7198-7199, 7299->7305, 7317-7327, 7335, 7336->7340, 7362-7363, 7439->7445, 7446-7456, 7463, 7502, 7510->7516, 7517-7527, 7534, 7599->7605, 7607-7618, 7624, 7664, 7672->7678, 7680-7691, 7697, 7787->7803, 7791-7792, 7797-7798, 7803->7809, 7821-7830, 7838, 7841->7845, 7864->7869, 7877-7878, 7961->7976, 7963->7976, 7967-7968, 7973-7974, 7976->7982, 7984-7995, 8001, 8043->8058, 8045->8058, 8049-8050, 8055-8056, 8058->8064, 8066-8077, 8083, 8125, 8134->8149, 8136->8149, 8140-8141, 8146-8147, 8149->8155, 8157-8168, 8174, 8231, 8240->8255, 8242->8255, 8246-8247, 8249-8250, 8255->8261, 8263-8274, 8280, 8374->8380, 8392-8401, 8409, 8410->8412, 8412->8416, 8435->8440, 8449-8450, 8530->8536, 8550-8555, 8593, 8601->8607, 8617-8626, 8690, 8753-8756, 8828-8829, 8835-8837, 8932->8935, 8935->8937, 8960-8961, 8970-8971, 8976-8977, 9020-9022, 9031, 9034, 9078-9086, 9092-9095, 9098, 9129-9133, 9171->9178, 9189->9197, 9211-9243, 9265, 9273-9288, 9322-9325, 9372, 9374, 9376, 9380, 9382, 9432->9439, 9447, 9461-9463, 9480-9511, 9567-9568, 9574, 9577-9583, 9617-9622, 9630-9633, 9636, 9684-9686, 9717-9721, 9814-9815, 9901-9916, 9959-9964, 9969-9972, 9976, 10019-10024, 10030-10033, 10036, 10068-10072, 10152-10153, 10155-10157, 10159-10160, 10240-10255, 10292-10297, 10302-10305, 10308, 10352-10357, 10363-10366, 10369, 10392-10434, 10462-10470, 10509, 10512-10520, 10526-10527, 10563-10586, 10621, 10755, 10869-10870, 10877, 10883-10895, 10906-10912, 11010-11177, 11232->11235, 11254->11265, 11268-11270, 11287, 11318-11319, 11334-11336, 11339-11348, 11395-11396, 11402-11403, 11441-11447, 11496, 11502-11505, 11508-11511, 11516-11519, 11577, 11581->11587, 11584-11585, 11593-11625, 11696-11701, 11709->11749, 11751-11753, 11804, 11810-11813, 11816-11819, 11824-11827, 11862->11883, 11935, 11939, 11973-11978, 12037-12042, 12074-12075, 12092-12093, 12244-12246, 12340-12341, 12364->12371, 12382->12390, 12385-12387, 12404-12436, 12446, 12455, 12509-12525, 12591-12594, 12600-12603, 12608->12615, 12623, 12634->12642, 12637-12639, 12655->12689, 12658->12660, 12661, 12663, 12665, 12667, 12668->12670, 12670->12676, 12677, 12679, 12683-12685, 12737-12742, 12768-12769, 12783-12802, 12828-12829, 12837-12845, 12851-12852, 12880, 12893-12894, 12905, 12919-12921, 12979, 12986-12990, 13014, 13019-13020, 13048, 13055-13061, 13087, 13090->13094, 13096-13097, 13121, 13126-13127, 13151, 13156-13160, 13184, 13189-13190, 13219->13223, 13243-13245, 13274->13278, 13299-13301, 13332->13336, 13355-13357, 13385->13389, 13416-13418, 13513->13517, 13550-13555, 13583->13587, 13611-13616, 13646->13650, 13695-13700, 13746-13761, 13789, 13885-13888, 13911-13914, 13946, 14076-14078, 14157-14159, 14194-14205, 14230-14231, 14247-14248, 14265-14293, 14343->14347, 14347->14349, 14349->14353, 14353->14357, 14357->14361, 14361->14365, 14365->14371, 14371->14385, 14414-14428, 14459-14481, 14619, 14622->14624, 14624->14626, 14626->14628, 14628->14631, 14642-14647, 14670-14687, 14717, 14727-14732, 14765-14782, 14887, 14889, 14895, 14900->14897, 14934-14951, 15043->15032, 15150->15147, 15211, 15295-15297, 15362-15364, 15432-15434, 15472-15489, 15554-15556, 15606-15608, 15678-15680, 15747->15746, 15758-15760, 15786-15787, 15864-15866, 15916-15918, 16008-16009, 16086-16088, 16138-16140, 16230-16231, 16272, 16282->16284, 16284->16286, 16287->16286, 16304-16306, 16327-16332, 16353-16358, 16379-16384, 16405-16410, 16435-16447 |
| mcpgateway/auth.py                                                             |      376 |        3 |      168 |        4 |     99% |516, 640->643, 745, 810 |
| mcpgateway/bootstrap\_db.py                                                    |      259 |       35 |       76 |        7 |     86% |118-124, 127-136, 189->191, 193-194, 198->201, 272->276, 302-303, 347-348, 352-355, 442-444, 503-507, 517-518, 543-546 |
| mcpgateway/cache/a2a\_stats\_cache.py                                          |       40 |        2 |        4 |        1 |     93% |   155-156 |
| mcpgateway/cache/admin\_stats\_cache.py                                        |      370 |        0 |       98 |        1 |     99% |  182->186 |
| mcpgateway/cache/auth\_cache.py                                                |      441 |        0 |      118 |        0 |    100% |           |
| mcpgateway/cache/global\_config\_cache.py                                      |       58 |        2 |       12 |        1 |     96% |   147-148 |
| mcpgateway/cache/metrics\_cache.py                                             |       67 |        4 |        8 |        0 |     95% |227-228, 243-244 |
| mcpgateway/cache/registry\_cache.py                                            |      308 |       20 |       68 |        9 |     92% |242->246, 600->exit, 608-609, 627->630, 630->638, 634-635, 638->657, 642-645, 649-654, 665, 671->663, 673->675, 675->663, 679-683 |
| mcpgateway/cache/resource\_cache.py                                            |       94 |        2 |       18 |        1 |     97% |  272, 332 |
| mcpgateway/cache/session\_registry.py                                          |      759 |      210 |      232 |       33 |     71% |345, 356-357, 368-369, 375-376, 382-387, 396-399, 431-432, 440->444, 448-449, 452-456, 458->415, 464-465, 496->511, 506->511, 541->549, 558->566, 562-563, 567-580, 589, 642-643, 740, 744->746, 780->782, 839-840, 855, 955-956, 968->exit, 1029, 1040, 1059-1060, 1077-1079, 1087-1088, 1185-1251, 1253->exit, 1305-1325, 1349-1358, 1426-1427, 1441, 1446->1462, 1463-1467, 1474-1476, 1490, 1593-1605, 1626, 1629-1631, 1634->exit, 1656, 1660-1661, 1708-1738, 1794-1795, 1802-1806, 1829-1831, 1842-1843, 1854-1858, 1866-1873, 1926, 1951, 1955, 1962-1968 |
| mcpgateway/cache/tool\_lookup\_cache.py                                        |      168 |        4 |       42 |        5 |     96% |154->157, 159->162, 275->exit, 279-280, 332->334, 335-336, 372->375 |
| mcpgateway/cli.py                                                              |      105 |       10 |       34 |        5 |     88% |120->123, 295->347, 299-301, 304-306, 331-335 |
| mcpgateway/cli\_export\_import.py                                              |      178 |       16 |       62 |        4 |     90% |90-112, 207->206, 248->251, 312->316 |
| mcpgateway/common/models.py                                                    |      344 |        1 |        2 |        1 |     99% |       925 |
| mcpgateway/common/validators.py                                                |      351 |       23 |      210 |       18 |     92% |406, 488, 597, 815, 1019, 1037, 1041->1051, 1047->1051, 1064, 1069-1070, 1153-1154, 1163-1165, 1173-1176, 1183->1187, 1188->1168, 1491, 1525, 1569, 1577, 1621, 1653 |
| mcpgateway/config.py                                                           |      839 |       78 |      128 |       32 |     87% |97-110, 577, 642-654, 691, 694->708, 726, 728->749, 767, 769, 772->781, 775, 779, 796->805, 799, 814->825, 817, 820, 837, 839->843, 844, 851, 855, 859, 862->866, 867, 1330-1344, 1681-1683, 1699, 1730, 1741-1742, 1745, 1925->exit, 2068-2088, 2124-2128, 2148, 2152, 2172-2173, 2222 |
| mcpgateway/db.py                                                               |     2164 |      224 |      378 |       70 |     86% |55, 84-102, 107->119, 136, 193-196, 203-204, 206-207, 213, 224, 240-247, 274->305, 347-351, 357-361, 383->389, 408-417, 436-445, 481-483, 519, 550->563, 553-559, 564-565, 590-597, 612-613, 629, 632-647, 661-694, 707-738, 766-781, 1003->1000, 1238->1237, 1781, 1783, 1875, 1877, 1887, 1967, 1969, 2929, 3003, 3043, 3057, 3071, 3085, 3118->3120, 3121->3111, 3336, 3368, 3410, 3426, 3442, 3458, 3490->3492, 3493->3483, 3514, 3679, 3747, 3779, 3821, 3837, 3853, 3869, 3901->3903, 3904->3894, 3925, 4052, 4084, 4126, 4142, 4158, 4174, 4206->4208, 4209->4199, 4230, 4432, 4467, 4579, 4589-4591, 4601-4603, 4613-4615, 4625-4629, 4639-4643, 4653-4657, 4974-4978, 5236, 5239, 5291, 5359, 5408-5412, 5471, 5485, 5508-5512, 6158, 6170, 6219, 6224, 6230->6235, 6232-6233, 6280, 6286->6291, 6288-6289 |
| mcpgateway/handlers/sampling.py                                                |       88 |        1 |       44 |        2 |     98% |214, 514->518 |
| mcpgateway/instrumentation/sqlalchemy.py                                       |       95 |        4 |       22 |        5 |     92% |81->85, 115-116, 140->145, 216->222, 218-219, 313->exit, 316->exit |
| mcpgateway/llm\_provider\_configs.py                                           |       60 |        2 |        0 |        0 |     97% |  520, 529 |
| mcpgateway/llm\_schemas.py                                                     |      228 |        7 |        6 |        0 |     94% |   100-109 |
| mcpgateway/main.py                                                             |     2835 |      541 |      838 |      174 |     79% |176, 181-182, 212, 329->324, 429->435, 489, 614->619, 687-691, 698->700, 776, 803-807, 817-827, 842-843, 852-853, 878->882, 941-942, 1003->1006, 1009->1015, 1016->1018, 1018->1021, 1030->exit, 1050->exit, 1089->1092, 1096, 1169, 1260->1262, 1264->1266, 1318->1325, 1323->1325, 1450->1452, 1488, 1498, 1518->1543, 1521-1522, 1529->1543, 1532-1535, 1546->1550, 1567, 1571-1572, 1584-1588, 1737-1738, 1771, 1781, 1793, 1797-1798, 1827->1834, 1836-1839, 1849-1852, 1859-1863, 1875->1877, 1885-1888, 1952->1972, 1962-1969, 2232, 2297->2299, 2384, 2394, 2425-2428, 2497, 2504, 2511, 2592, 2634-2637, 2662-2663, 2701, 2704-2705, 2744, 2757, 2758->2762, 2770-2774, 2831-2832, 2838->2859, 2840->2859, 2843->2859, 2852->2859, 2855-2856, 2860, 2866-2873, 2912, 2948-2949, 2987-2988, 3037, 3040, 3048-3049, 3068, 3087->3089, 3119, 3126, 3136-3137, 3181, 3188, 3195, 3201, 3219-3224, 3258, 3279-3280, 3313, 3345-3346, 3375, 3382-3387, 3420, 3427, 3429, 3435, 3446-3449, 3496, 3504-3505, 3507, 3516, 3524, 3546-3549, 3552-3554, 3596, 3610, 3635, 3646-3649, 3682-3684, 3748-3751, 3787, 3828-3831, 3856-3857, 3893, 3900, 3902, 3952-3955, 3980-3981, 4020, 4031, 4070->4072, 4117, 4124, 4131, 4154-4162, 4235-4249, 4278-4282, 4336-4337, 4375-4380, 4438-4441, 4466-4467, 4506, 4514-4515, 4517, 4526, 4534, 4555-4558, 4605, 4612, 4619, 4643, 4646, 4649-4650, 4656-4657, 4716-4724, 4779-4782, 4841-4849, 4884, 4887-4890, 4942-4943, 4968-4969, 5013, 5046-5049, 5090, 5097, 5104, 5133, 5159-5160, 5220, 5260-5265, 5297-5312, 5354-5388, 5437-5445, 5489-5497, 5585-5613, 5616-5619, 5626->5631, 5632-5641, 5672, 5683->6155, 5689-5690, 5692, 5698, 5881-5883, 5984->5986, 6085, 6088, 6150, 6165-6166, 6197-6199, 6205-6206, 6215-6217, 6240, 6242, 6257-6262, 6295-6299, 6305, 6308, 6321, 6322->6326, 6354-6358, 6403-6405, 6458->6462, 6491->6508, 6502-6505, 6539-6540, 6581-6582, 6614-6646, 6683, 6689, 6723, 6729, 6778->6781, 6783, 6787, 6791, 6795, 6814-6819, 6855, 6856->6860, 6868-6873, 6916, 6920, 6930-6931, 6933-6934, 6936-6937, 6959-6965, 6980-6983, 6999-7002, 7031-7034, 7039-7042, 7047->7055, 7059, 7076-7083, 7086-7089, 7099-7102, 7112-7115, 7125-7128, 7137-7138, 7147-7148, 7152-7173, 7177-7184, 7194-7197, 7210, 7230-7231, 7264-7284 |
| mcpgateway/middleware/auth\_middleware.py                                      |       64 |        0 |       14 |        0 |    100% |           |
| mcpgateway/middleware/compression.py                                           |       22 |        0 |        4 |        0 |    100% |           |
| mcpgateway/middleware/correlation\_id.py                                       |       28 |        0 |        6 |        0 |    100% |           |
| mcpgateway/middleware/db\_query\_logging.py                                    |      183 |       27 |       60 |       13 |     80% |99, 160, 162, 170->180, 186->192, 187->186, 193, 199->201, 252-278, 294, 341, 361->365, 426, 427->431, 446-447 |
| mcpgateway/middleware/http\_auth\_middleware.py                                |       58 |        0 |       22 |        2 |     98% |90->95, 118->122 |
| mcpgateway/middleware/observability\_middleware.py                             |       94 |       13 |       22 |        8 |     82% |89->93, 96->102, 149-153, 163->175, 171-172, 175->188, 185-186, 192->211, 207-208, 211->218, 214-215, 224->226 |
| mcpgateway/middleware/path\_filter.py                                          |       61 |        4 |       10 |        0 |     94% |137-138, 153-154 |
| mcpgateway/middleware/protocol\_version.py                                     |       29 |        0 |       10 |        0 |    100% |           |
| mcpgateway/middleware/rbac.py                                                  |      233 |        0 |       92 |        0 |    100% |           |
| mcpgateway/middleware/request\_context.py                                      |        7 |        0 |        2 |        0 |    100% |           |
| mcpgateway/middleware/request\_logging\_middleware.py                          |      227 |       54 |       82 |       15 |     75% |156, 272-274, 282, 284->289, 286->289, 290, 299-300, 342->350, 344-347, 366-368, 372-387, 394->416, 413-414, 431->506, 444-445, 458->477, 475-476, 481-500, 504, 532, 550-552, 570, 580-604, 611-630, 644-650 |
| mcpgateway/middleware/security\_headers.py                                     |       61 |        0 |       40 |        0 |    100% |           |
| mcpgateway/middleware/token\_scoping.py                                        |      376 |       59 |      190 |       29 |     83% |137->132, 160, 233->224, 382, 414-415, 427->429, 440->443, 513, 553, 561-562, 575-576, 598-599, 606-607, 614-615, 630-631, 673-674, 698-699, 706-707, 712-713, 722-737, 744-745, 752-753, 758-759, 763-769, 778-787, 796-799, 872, 918->923 |
| mcpgateway/middleware/validation\_middleware.py                                |      100 |       11 |       52 |        6 |     88% |93-98, 118->123, 120, 196, 211, 213, 229->233, 238-239 |
| mcpgateway/observability.py                                                    |      238 |       18 |       98 |       15 |     90% |23-28, 68->97, 92-94, 163-164, 170-171, 185->184, 232->231, 245, 269->268, 281-282, 289-290, 297-298, 308->323, 453->455, 455->462, 494->498, 514->516, 519->522 |
| mcpgateway/plugins/framework/base.py                                           |      153 |       33 |       42 |        4 |     75% |396->408, 409, 443, 454, 486-556 |
| mcpgateway/plugins/framework/constants.py                                      |       26 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/decorator.py                                      |       21 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/errors.py                                         |       12 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/client.py                           |      108 |        0 |       26 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/proto/plugin\_service\_pb2.py       |       11 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/proto/plugin\_service\_pb2\_grpc.py |       58 |        0 |        0 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/server/runtime.py                   |       99 |        0 |       20 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/server/server.py                    |       88 |        0 |       16 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/grpc/tls\_utils.py                       |       44 |        0 |       10 |        0 |    100% |           |
| mcpgateway/plugins/framework/external/mcp/client.py                            |      286 |       61 |       98 |       31 |     74% |81, 83->88, 85, 104-105, 108-114, 132, 136, 140, 147-151, 164, 195->198, 200, 203->206, 206->exit, 222->224, 224->226, 238-240, 254, 283, 286, 302-305, 311->exit, 330-342, 362, 365, 371, 374-375, 383->369, 389-391, 404, 409, 414-416, 423->425, 427-428, 436->439, 439->441, 450, 459, 463-464, 488 |
| mcpgateway/plugins/framework/external/mcp/server/runtime.py                    |      152 |       28 |       42 |       15 |     77% |133, 205->207, 207->209, 210, 254->257, 259->262, 265->267, 269, 309, 318-319, 327, 336, 381, 392-393, 401, 408, 421-424, 438, 481-482, 489-493, 533, 538-540 |
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
| mcpgateway/plugins/framework/manager.py                                        |      218 |       20 |       78 |       10 |     89% |152, 257, 264->270, 285->293, 320-354, 535-536, 585-586, 640, 743, 759-763 |
| mcpgateway/plugins/framework/memory.py                                         |       90 |        0 |       40 |        0 |    100% |           |
| mcpgateway/plugins/framework/models.py                                         |      572 |       46 |      228 |       33 |     89% |371, 373, 382, 417, 423, 434-439, 476-478, 502, 509->512, 558, 574->583, 579, 581->583, 622, 627, 629, 647, 668, 674, 689-690, 756, 813, 884, 886, 890, 904-905, 981, 983, 987, 997-1002, 1057->1060, 1103, 1105, 1130-1139, 1199, 1232 |
| mcpgateway/plugins/framework/registry.py                                       |       66 |        0 |       18 |        1 |     99% |  151->155 |
| mcpgateway/plugins/framework/utils.py                                          |       52 |        1 |       30 |        2 |     96% |138, 239->249 |
| mcpgateway/plugins/tools/cli.py                                                |       51 |        3 |        2 |        0 |     94% |168-169, 224 |
| mcpgateway/plugins/tools/models.py                                             |        7 |        0 |        0 |        0 |    100% |           |
| mcpgateway/reverse\_proxy.py                                                   |      333 |       21 |       94 |       16 |     91% |52-53, 58-59, 65-66, 179->185, 226, 236, 247-250, 322, 352, 355->359, 360->362, 470->474, 472->474, 477, 548->559, 559->563, 573, 579, 712, 723, 767-768 |
| mcpgateway/routers/auth.py                                                     |       58 |        0 |        8 |        0 |    100% |           |
| mcpgateway/routers/cancellation\_router.py                                     |       45 |        3 |        6 |        1 |     92% |96-98, 126 |
| mcpgateway/routers/email\_auth.py                                              |      268 |        0 |       44 |        0 |    100% |           |
| mcpgateway/routers/llm\_admin\_router.py                                       |      226 |       43 |       42 |        6 |     79% |170-171, 265-266, 300-301, 328, 366-367, 388-389, 417-418, 466-467, 576->579, 603-606, 691-692, 720-723, 748-761, 775-788, 830, 834, 851, 870-872 |
| mcpgateway/routers/llm\_config\_router.py                                      |      184 |        0 |        2 |        0 |    100% |           |
| mcpgateway/routers/llm\_proxy\_router.py                                       |       46 |       13 |        6 |        1 |     73% |87, 106-126 |
| mcpgateway/routers/llmchat\_router.py                                          |      337 |       68 |      106 |       18 |     77% |36-37, 66-68, 291, 392, 502, 551-553, 568-572, 578-582, 589, 590->585, 595-602, 706-707, 723-730, 737->746, 740->738, 742-743, 751-753, 826-827, 828->819, 833-835, 837-839, 844-848, 920, 923, 932, 953-964, 1022, 1151->1155 |
| mcpgateway/routers/log\_search.py                                              |      327 |       32 |      104 |       29 |     84% |74, 82->77, 98->100, 127-136, 139-141, 144->147, 153, 155, 169-174, 178->exit, 379, 395, 470->490, 473->490, 482->490, 539-541, 580->582, 582->584, 584->586, 586->588, 588->591, 591->594, 615-617, 658->660, 660->662, 662->664, 664->666, 666->668, 668->671, 671->674, 696-698, 732->746, 780-782 |
| mcpgateway/routers/metrics\_maintenance.py                                     |       93 |        0 |       10 |        0 |    100% |           |
| mcpgateway/routers/oauth\_router.py                                            |      236 |        0 |       66 |        4 |     99% |127->131, 198->205, 369->377, 585->588 |
| mcpgateway/routers/observability.py                                            |      148 |        7 |       32 |        4 |     94% |52-53, 564, 568, 622->exit, 648-649, 821 |
| mcpgateway/routers/rbac.py                                                     |      212 |       34 |        8 |        1 |     84% |61, 63-70, 121-123, 195-197, 201-203, 245-247, 285-287, 329-331, 367-370, 422-424 |
| mcpgateway/routers/reverse\_proxy.py                                           |      203 |       48 |       48 |       11 |     75% |193, 195-202, 205-219, 227-229, 281-282, 316, 324->321, 417-420, 423, 439, 445, 453-454, 484-504 |
| mcpgateway/routers/server\_well\_known.py                                      |       39 |        0 |       10 |        0 |    100% |           |
| mcpgateway/routers/sso.py                                                      |      243 |        2 |       56 |        3 |     98% |187->191, 191->208, 609-611 |
| mcpgateway/routers/teams.py                                                    |      411 |       90 |       84 |       23 |     77% |262-264, 354, 377-382, 418-420, 471, 496, 501-503, 532, 536, 541, 547-554, 584, 591-593, 629, 652-657, 683, 712-716, 748-753, 782, 787, 791, 796-800, 833, 860-862, 893, 902, 907, 914-916, 947, 951, 972-976, 1009, 1013, 1018, 1031-1035, 1068, 1077, 1084-1086 |
| mcpgateway/routers/tokens.py                                                   |      180 |        5 |       44 |        5 |     96% |74, 98, 351, 633, 638 |
| mcpgateway/routers/toolops\_router.py                                          |       50 |        2 |        0 |        0 |     96% |   138-139 |
| mcpgateway/routers/well\_known.py                                              |      108 |        4 |       50 |        5 |     94% |68, 149, 173, 184->187, 188 |
| mcpgateway/schemas.py                                                          |     2731 |      187 |      612 |      117 |     90% |400, 576->580, 754, 814, 841->845, 945, 978-980, 1018, 1022, 1062-1063, 1064->1073, 1068-1069, 1150, 1153->1155, 1155->1157, 1175, 1178, 1217, 1242->1239, 1244, 1264->1263, 1266, 1648, 2035, 2338-2340, 2620-2622, 2729, 2773, 2780, 2801, 2803, 2940-2942, 2993, 3023, 3030, 3034, 3038, 3045, 3049, 3053, 3062, 3067, 3074, 3094, 3215->3234, 3219->3234, 3227->3226, 3230->3233, 3313, 3318, 3328, 3332, 3339, 3343->3353, 3346, 3517, 3574, 3608, 3778-3780, 3829, 3843-3845, 3957-3959, 4066-4069, 4078, 4302-4304, 4336, 4402, 4432, 4443, 4450, 4457-4473, 4477, 4484, 4505, 4507, 4510->4520, 4580, 4639-4641, 4656, 4675, 4738-4744, 4751, 4763-4812, 4816, 4823, 4843, 4956->4975, 4960-4974, 5043, 5049, 5052, 5067, 5071, 5077, 5080->5086, 5083, 5114, 5147, 5163-5164, 5304, 5648, 5667->5671, 5692, 5694, 5737, 5744, 5746, 5762->5768, 5764->5768, 5767, 6097, 6103, 6139, 6148, 6771, 6786, 6788-6790, 6820, 6837-6841, 6855, 6857-6859 |
| mcpgateway/scripts/validate\_env.py                                            |       68 |        6 |       36 |        2 |     88% |144, 243-249 |
| mcpgateway/services/a2a\_service.py                                            |      618 |      124 |      242 |       58 |     75% |162->exit, 168->exit, 287->289, 355->361, 358->361, 395, 398->407, 403-404, 409->422, 414, 472-473, 536-544, 641, 648, 655, 716->723, 753, 768-777, 786, 794, 811-814, 916, 921, 943, 994->997, 998-1013, 1028-1029, 1032-1033, 1038-1039, 1045->1023, 1070-1071, 1074->1083, 1080-1081, 1091, 1093->1125, 1102-1105, 1111-1122, 1125->1130, 1131, 1133, 1135, 1137, 1168-1169, 1177-1178, 1183-1185, 1211, 1215-1219, 1223, 1279->1282, 1366, 1370, 1377, 1395-1406, 1415-1418, 1552-1553, 1560->1566, 1563-1564, 1585->1591, 1588, 1618->1621, 1658->1660, 1683, 1687->1698, 1694, 1699-1713 |
| mcpgateway/services/argon2\_service.py                                         |       91 |        0 |       20 |        2 |     98% |253->247, 257->260 |
| mcpgateway/services/audit\_trail\_service.py                                   |      124 |       14 |       48 |       16 |     81% |134->138, 190->192, 215, 222, 264->273, 275, 276->280, 282, 284, 371-375, 406->410, 413->415, 416, 418, 420, 422, 424 |
| mcpgateway/services/cancellation\_service.py                                   |      150 |       17 |       34 |        7 |     87% |59, 69-70, 78-79, 93, 113, 132->105, 140-141, 144->exit, 149-152, 167, 169, 177->184, 180, 272 |
| mcpgateway/services/catalog\_service.py                                        |      265 |       42 |      106 |       17 |     80% |67->73, 78-85, 102-103, 131, 138->166, 159-163, 199->203, 221-222, 245->244, 273->289, 278, 281, 320-321, 368-370, 397->400, 426->432, 434, 438->441, 452-465, 488->487, 521-523, 550-554 |
| mcpgateway/services/completion\_service.py                                     |       71 |        2 |       26 |        1 |     97% |  123, 127 |
| mcpgateway/services/dcr\_service.py                                            |      158 |       21 |       44 |        9 |     85% |51, 91->96, 115, 129, 139, 213, 228, 314, 317, 344-347, 363-364, 367-368, 383-387 |
| mcpgateway/services/elicitation\_service.py                                    |      133 |        3 |       44 |        6 |     95% |87->exit, 93->101, 103->102, 231-232, 241->239, 243->239, 286 |
| mcpgateway/services/email\_auth\_service.py                                    |      457 |       72 |      132 |       13 |     83% |252, 390-391, 414, 519, 543-544, 563-566, 570-573, 617-618, 655, 705-707, 716-726, 732, 741->754, 754->756, 760, 783-784, 795, 832-926, 957->965, 1056-1057, 1065->1069, 1241-1242 |
| mcpgateway/services/encryption\_service.py                                     |       66 |        3 |        8 |        2 |     93% |189, 195->202, 197-199 |
| mcpgateway/services/event\_service.py                                          |       99 |       11 |       22 |        3 |     88% |215, 233-235, 251-252, 254-255, 261-262, 264-265, 269->exit, 297->exit |
| mcpgateway/services/export\_service.py                                         |      340 |       35 |      136 |       27 |     84% |170, 191, 212, 233, 254, 349->352, 352->355, 368->372, 439->452, 442->452, 444->452, 498->508, 500->508, 576->586, 650->649, 760->749, 764->768, 789, 797-825, 842, 849-870, 888, 896-910, 927, 935-951, 968, 975-985 |
| mcpgateway/services/gateway\_service.py                                        |     2210 |      492 |      910 |      157 |     74% |77-79, 514->exit, 565->570, 629->620, 647->620, 654->620, 739->750, 746->750, 760->764, 793->823, 911->908, 916-919, 998->995, 1003-1005, 1537->1544, 1555-1569, 1581-1585, 1597, 1648-1652, 1680-1737, 1798->1801, 1815, 1825->1847, 1834-1840, 1859-1862, 1870->1892, 1883, 1907, 1909, 1911, 1913-1922, 1934-1935, 1940, 1953-1958, 1964, 1993-1994, 1997->2006, 2002-2003, 2011->2018, 2015, 2020->2038, 2026-2031, 2034->2038, 2038->2055, 2044-2050, 2076-2078, 2092-2098, 2117-2122, 2128-2132, 2154, 2156, 2158, 2166-2169, 2171-2174, 2176-2179, 2189, 2194, 2196, 2198, 2200, 2204, 2476-2480, 2483->2725, 2502-2511, 2528-2534, 2543-2547, 2553-2558, 2564-2568, 2573, 2590, 2592, 2594, 2602-2605, 2607-2610, 2612-2617, 2656->2660, 2660->2666, 2670->2675, 2679->2683, 2729-2740, 2859-2864, 2868-2872, 2883, 3044, 3053, 3059-3093, 3098, 3100, 3117-3119, 3125-3127, 3131, 3136-3137, 3178->3193, 3184-3191, 3199-3317, 3350, 3356, 3364-3367, 3479-3480, 3514-3523, 3543-3547, 3549, 3568, 3595-3627, 3633-3638, 3643, 3654-3656, 3659-3695, 3699-3701, 3707->3714, 3710-3711, 3718->3736, 3723, 3727->3730, 3751-3752, 3755-3756, 3760-3761, 3838->3837, 3842->3839, 3878->exit, 3977, 3978->3988, 4065->4067, 4068, 4073, 4089-4100, 4103, 4138-4147, 4153->4158, 4155-4156, 4168-4170, 4180->4133, 4184-4185, 4188-4189, 4279-4290, 4450, 4458-4459, 4484->4486, 4486->4456, 4537, 4545-4546, 4556->4565, 4565->4543, 4587-4589, 4613, 4621-4622, 4632->4639, 4639->4619, 4662-4664, 4812-4821, 4866-4868, 4905->4917, 4908-4914, 4918->4929, 4921-4926, 4982->4984, 5230->5282, 5240->5242, 5268->5272, 5272->5275, 5278-5279, 5284->5308, 5291->5293, 5360-5361, 5392->5446, 5404->5406, 5432->5436, 5436->5439, 5442-5443, 5447->5473, 5521, 5549->5553, 5554->5608, 5563->5566, 5566->5568, 5583-5584, 5594->5598, 5598->5601, 5604-5605, 5609->5625, 5619, 5622-5623 |
| mcpgateway/services/grpc\_service.py                                           |      229 |        8 |       80 |        8 |     95% |26-31, 73->75, 214->217, 257->261, 305, 438-439, 465->464, 486->485, 494->493, 600->604 |
| mcpgateway/services/http\_client\_service.py                                   |       79 |       18 |       18 |        5 |     68% |55, 91->97, 93->95, 95->97, 150, 166-177, 181-186, 191-193, 280-282 |
| mcpgateway/services/import\_service.py                                         |      800 |      103 |      336 |       53 |     85% |296->exit, 625, 631, 633, 634->exit, 667-668, 701->exit, 763->exit, 825->exit, 856-857, 874->exit, 905-906, 923->exit, 952-955, 958, 1011-1014, 1017, 1041-1044, 1070-1073, 1076, 1100-1103, 1214-1228, 1230->1257, 1236->1257, 1243->1257, 1245->1257, 1283-1297, 1298->1321, 1303->1321, 1309->1321, 1311->1321, 1345->1370, 1357->1360, 1360->1363, 1364-1365, 1386->1401, 1391->1393, 1393->1396, 1397, 1415->1422, 1444->1451, 1526->1525, 1569->1573, 1573->1577, 1623-1624, 1644, 1652->1651, 1655->1653, 1659->1646, 1680, 1686->1682, 1709->1723, 1716->1714, 1719->1723, 1723->1741, 1730->1728, 1733->1741, 1753-1767, 1780-1799, 1812-1813, 1817-1818, 1832->1827, 1836-1841, 1845-1847, 1850-1851, 1855-1856 |
| mcpgateway/services/llm\_provider\_service.py                                  |      276 |        9 |      100 |       17 |     93% |92->exit, 98->exit, 284->286, 507->509, 509->511, 511->513, 513->515, 515->517, 517->519, 519->521, 521->523, 523->525, 525->527, 527->529, 529->532, 569, 691-692, 700-705 |
| mcpgateway/services/llm\_proxy\_service.py                                     |      280 |        0 |      140 |        0 |    100% |           |
| mcpgateway/services/log\_aggregator.py                                         |      355 |       13 |      136 |       22 |     92% |64, 66, 71->75, 78, 83, 118->120, 124->126, 256->223, 374->335, 383->385, 405, 408->412, 434->431, 437->439, 442->444, 466->470, 483->485, 488->490, 549->525, 566-569, 596->600, 612->614, 616->618, 620-623 |
| mcpgateway/services/log\_storage\_service.py                                   |      154 |        1 |       44 |        5 |     97% |216->218, 245->254, 248->254, 257->exit, 346 |
| mcpgateway/services/logging\_service.py                                        |      235 |        8 |       54 |        3 |     96% |124->exit, 131-133, 158->178, 261-263, 455-457, 464-465, 669->674 |
| mcpgateway/services/mcp\_client\_chat\_service.py                              |      848 |      115 |      300 |       70 |     83% |64, 74, 84, 178->180, 210, 240, 665->668, 792->823, 806->818, 905->921, 910, 914->916, 917-919, 997->1025, 1013, 1017->1020, 1086, 1116->1141, 1127->1136, 1137-1139, 1233->1269, 1238, 1240, 1242, 1254->1264, 1265-1267, 1365->1401, 1375->1377, 1377->1379, 1388->1397, 1398-1400, 1489, 1552->1556, 1558-1559, 1564, 1587, 1593, 1614, 1618, 1623, 1625, 1627, 1642, 1660->1663, 1666, 1670, 1688, 1718, 1723, 1941-1942, 2094->2088, 2192->2197, 2194->2197, 2198, 2239->2243, 2247-2249, 2283, 2295-2297, 2431-2432, 2439-2448, 2560->2554, 2602, 2626->2622, 2628->2622, 2630->2622, 2635->2639, 2641-2643, 2687, 2691, 2724, 2726, 2742-2743, 2762->2765, 2779, 2782->2788, 2785-2786, 2802-2803, 2818-2819, 2839-2840, 2857->2747, 2860-2861, 2863->2747, 2865->2747, 2867->2747, 2871-2873, 2887->2889, 2899->2907, 2931-2933, 2954-2957, 2976-2980, 3013-3029, 3083-3100 |
| mcpgateway/services/mcp\_session\_pool.py                                      |      843 |      241 |      236 |       34 |     70% |82-83, 88, 418->423, 519, 533-537, 544-546, 586-587, 603, 624-653, 704->744, 711->716, 717-741, 806->815, 811-813, 835->838, 873->875, 875->877, 890->exit, 910, 935, 937->925, 946->939, 952-953, 1030-1032, 1100, 1111, 1121, 1155, 1167->1173, 1171-1172, 1177-1178, 1224-1227, 1237-1253, 1271-1272, 1286-1291, 1311-1342, 1354, 1357, 1365-1371, 1402, 1455, 1463-1466, 1488-1522, 1567-1574, 1577-1578, 1603-1664, 1678, 1710-1782, 1918->1943, 1938, 1979-1980, 1991-2001, 2020, 2033-2042 |
| mcpgateway/services/metrics.py                                                 |       50 |        0 |       14 |        1 |     98% |  121->130 |
| mcpgateway/services/metrics\_buffer\_service.py                                |      256 |       52 |       48 |       10 |     80% |147->exit, 160->168, 293-303, 364-375, 385->exit, 394, 404-407, 473->489, 489->505, 506, 522, 538, 575-587, 604-616, 633-645, 662-674, 693-706, 737-738 |
| mcpgateway/services/metrics\_cleanup\_service.py                               |      185 |       31 |       40 |        9 |     80% |198->exit, 211->218, 231->exit, 240, 243-251, 256-259, 285, 302->321, 308, 368-379, 384-387, 392, 431-441 |
| mcpgateway/services/metrics\_query\_service.py                                 |      172 |       18 |       42 |       10 |     86% |195->202, 236, 308, 339, 365, 457, 563-580, 586, 589, 597-615 |
| mcpgateway/services/metrics\_rollup\_service.py                                |      345 |       22 |       86 |       15 |     90% |188->190, 217->exit, 230->237, 269, 275-276, 284, 290, 307-310, 479->518, 512->518, 514->518, 596->601, 640, 683, 688->694, 706-714, 730-732, 928 |
| mcpgateway/services/notification\_service.py                                   |      187 |        8 |       38 |        4 |     95% |59, 215, 481-487, 520->540, 529, 537-538 |
| mcpgateway/services/oauth\_manager.py                                          |      583 |        0 |      218 |        0 |    100% |           |
| mcpgateway/services/observability\_service.py                                  |      340 |       10 |      172 |       51 |     87% |249->253, 254->257, 317->320, 486, 676->679, 684->688, 688->692, 694->710, 837->841, 939->955, 1149->1151, 1151->1155, 1155->1157, 1157->1161, 1161->1163, 1163->1165, 1165->1169, 1169->1171, 1171->1175, 1175->1177, 1177->1181, 1181->1183, 1183->1187, 1187->1191, 1191->1198, 1198->1206, 1202->1206, 1206->1214, 1215, 1217, 1220-1221, 1323->1325, 1325->1329, 1329->1331, 1331->1335, 1335->1337, 1337->1341, 1341->1345, 1345->1347, 1347->1351, 1351->1353, 1353->1355, 1355->1359, 1359->1361, 1361->1365, 1365->1367, 1367->1371, 1371->1376, 1376->1381, 1382, 1384, 1387-1388, 1411 |
| mcpgateway/services/performance\_service.py                                    |      344 |       35 |      104 |       23 |     86% |60->65, 74-76, 84-86, 94-96, 162, 205-206, 264-265, 269-271, 293-294, 300-301, 351-352, 361-362, 388->387, 395, 399, 402->387, 405->385, 412->409, 415->385, 426->436, 429, 455->463, 483, 500->508, 504-506, 568, 570-571, 604->607, 645, 709->711, 711->713, 713->715, 715->699 |
| mcpgateway/services/performance\_tracker.py                                    |      124 |       15 |       38 |        9 |     84% |86->exit, 117-119, 134-146, 174, 260-261, 278, 282, 301->304, 335, 339, 349 |
| mcpgateway/services/permission\_service.py                                     |      164 |       11 |       64 |        3 |     91% |177-192, 346->351, 638 |
| mcpgateway/services/personal\_team\_service.py                                 |       71 |        0 |        8 |        0 |    100% |           |
| mcpgateway/services/plugin\_service.py                                         |      107 |        3 |       54 |       10 |     92% |34->39, 105->109, 113, 119->144, 121->120, 138->142, 182->185, 189->208, 192, 231 |
| mcpgateway/services/prompt\_service.py                                         |      860 |      165 |      316 |       48 |     77% |208-209, 265->272, 268, 284->287, 317-326, 479->481, 530, 534-535, 780->782, 811->813, 813->815, 852->855, 857->764, 886-887, 1037-1038, 1057, 1065-1073, 1087, 1178-1241, 1295->1300, 1302-1323, 1332->1336, 1343-1344, 1359-1369, 1421->1434, 1426-1428, 1500-1517, 1540-1554, 1557-1568, 1592, 1599-1606, 1626-1627, 1631-1639, 1680-1683, 1707-1708, 1712-1722, 1800-1810, 1819, 1822-1827, 1832->1834, 1848->1850, 1873, 1924-1937, 1939-1953, 2044-2047, 2057, 2059->2103, 2066->2070, 2106-2117, 2120, 2172, 2356->exit, 2464->2471, 2475, 2485->2492, 2581-2586, 2623->2630, 2626, 2636->2639 |
| mcpgateway/services/resource\_service.py                                       |     1154 |      251 |      440 |       70 |     76% |81-82, 174->194, 237->245, 240, 258->261, 338-339, 342->344, 345-347, 449, 747->689, 823-828, 904->920, 910-914, 1000-1001, 1024, 1032-1041, 1057, 1119-1120, 1190->1193, 1194-1203, 1212, 1220, 1231-1232, 1241-1242, 1305-1329, 1337->1341, 1348-1349, 1364-1374, 1387-1397, 1531-1532, 1548, 1585-1601, 1614->1621, 1616-1617, 1624, 1674-1684, 1698-1731, 1736, 1738, 1781-1823, 1864, 1870-1875, 1878-1888, 1899-1900, 1908-1909, 1914, 1920-1923, 1926-1955, 2061-2078, 2120, 2125, 2129-2134, 2161-2162, 2174, 2198->2206, 2200->2202, 2208, 2215, 2218-2219, 2223, 2232, 2239-2246, 2250-2253, 2296-2308, 2311, 2316, 2346-2347, 2352-2363, 2407-2410, 2420, 2430->2435, 2481-2492, 2495, 2658-2660, 2663-2667, 2676, 2720, 2794-2808, 2810-2826, 2828-2843, 3075->3082, 3180->exit, 3227, 3236, 3245-3246, 3251, 3465, 3468, 3509->3516, 3512, 3532->3535 |
| mcpgateway/services/role\_service.py                                           |      174 |        1 |       78 |        2 |     99% |428, 447->460 |
| mcpgateway/services/root\_service.py                                           |       96 |        2 |       20 |        1 |     97% |81-82, 275->279 |
| mcpgateway/services/security\_logger.py                                        |      144 |       30 |       40 |        8 |     76% |106-111, 118, 206->210, 233->254, 290-321, 336, 349->351, 458-459, 492, 542-582, 596->598 |
| mcpgateway/services/server\_service.py                                         |      605 |      101 |      258 |       40 |     81% |178, 182-183, 215->222, 218, 234->237, 314->334, 325->328, 531-536, 549-554, 559, 567-572, 577, 585-595, 598-602, 665-680, 769-774, 798-812, 822-828, 840, 893-897, 939->942, 943-952, 963, 972, 987-988, 1161->1170, 1167, 1183->1187, 1191, 1206, 1216, 1235, 1302, 1328, 1479-1482, 1484, 1492, 1494->1536, 1553-1561, 1564, 1567, 1712, 1720-1727, 1857->1864, 1860, 1880->1883, 1963, 1969->1972, 1973 |
| mcpgateway/services/sso\_service.py                                            |      411 |       87 |      210 |       35 |     75% |75, 86-90, 260, 263->267, 268->267, 390, 463-464, 470-471, 479-485, 498-517, 531-599, 682->685, 717->721, 723->726, 757, 765, 769, 780->796, 800->809, 804, 806->809, 809->893, 816, 820-822, 825->856, 832, 835->856, 869, 877, 879->885, 882, 885->893, 887->893, 988, 1009->1006, 1033-1035, 1041->1028, 1045, 1050->1054, 1090-1091, 1101-1102 |
| mcpgateway/services/structured\_logger.py                                      |      161 |       19 |       34 |       11 |     85% |35, 127->131, 135->141, 137-138, 144->151, 148-149, 174, 178, 208-209, 215, 235, 245, 311->315, 316, 413, 422, 431, 441, 451, 476 |
| mcpgateway/services/support\_bundle\_service.py                                |      117 |       15 |       28 |        3 |     85% |257-258, 305->307, 307->310, 336-354 |
| mcpgateway/services/system\_stats\_service.py                                  |      100 |       11 |        4 |        0 |     86% |81-86, 164-172 |
| mcpgateway/services/tag\_service.py                                            |      143 |        9 |       72 |        5 |     92% |157, 208-211, 317, 416, 423-426 |
| mcpgateway/services/team\_invitation\_service.py                               |      190 |       33 |       56 |        5 |     83% |196-213, 309-334, 373-376, 415-418, 462->465 |
| mcpgateway/services/team\_management\_service.py                               |      679 |      100 |      182 |       40 |     83% |178->183, 210-211, 237-238, 352, 407, 420-424, 484->492, 512-513, 547-548, 552-553, 559-560, 566->571, 581-582, 622-623, 627-628, 634-635, 641->646, 653-654, 661-664, 676-680, 702->718, 712-714, 728->732, 771-774, 784-789, 848-862, 881->894, 890-891, 923, 926, 956-957, 965-971, 990->996, 994, 1003->1006, 1051->1054, 1076->1080, 1116, 1119, 1121->1124, 1124->1133, 1159, 1162, 1164->1167, 1167->1176, 1202->1204, 1339-1340, 1404->1407, 1579-1580, 1614-1615, 1622-1633, 1639->1669, 1659-1667, 1690-1692 |
| mcpgateway/services/token\_catalog\_service.py                                 |      254 |       28 |       86 |       10 |     87% |338, 342, 346, 350, 358-363, 565, 570->573, 713-714, 739-760, 854->858, 878, 969->968 |
| mcpgateway/services/token\_storage\_service.py                                 |      183 |       33 |       56 |        9 |     77% |158->160, 201-205, 209->219, 211-215, 231-241, 246-256, 259-261, 281-282, 298->302, 335 |
| mcpgateway/services/tool\_service.py                                           |     1602 |      424 |      618 |       89 |     71% |194-200, 286-289, 427-428, 491->497, 494, 507->510, 588-590, 809-818, 839-840, 925-932, 936, 941->947, 943-944, 948-957, 962-963, 979-980, 1056->1059, 1221-1238, 1341, 1432->1408, 1545->1556, 1578->1582, 1775, 1789->1791, 1805, 1812, 1868-1869, 1920, 1947-1952, 1962->1964, 1964->1966, 2027-2030, 2037-2038, 2051->2054, 2058-2062, 2068->2071, 2075, 2078-2081, 2084, 2088, 2094, 2101, 2115-2116, 2226, 2356-2359, 2369, 2387->2393, 2398, 2445-2456, 2459, 2547, 2549, 2551, 2565-2566, 2575, 2577, 2605->2609, 2661-2672, 2681->2688, 2684-2686, 2703-2724, 2742-2748, 2768-2793, 2841-2845, 2849->2851, 2862->2866, 2900-2939, 2949-2950, 2959-2960, 2967-2968, 2980-3000, 3006-3008, 3024-3028, 3041, 3062-3081, 3136-3141, 3145-3153, 3176-3238, 3281-3286, 3291-3300, 3323-3385, 3392->3394, 3394->3396, 3403->3410, 3407->3410, 3424, 3430-3539, 3568, 3573-3577, 3588-3589, 3614-3630, 3634-3635, 3651-3652, 3749, 3769-3780, 3782, 3807->3810, 3836, 3849->3851, 3908-3922, 4043-4053, 4075->exit, 4192->4199, 4195, 4205->4208, 4276, 4289, 4368-4408, 4432-4439, 4457-4502, 4530-4531, 4536-4538, 4558, 4560, 4563-4575, 4582 |
| mcpgateway/toolops/toolops\_altk\_service.py                                   |      135 |       18 |       32 |       11 |     83% |32-37, 66, 117, 120, 123, 126, 157->188, 169->188, 170->188, 173->188, 177-179, 249-250, 255->268, 265-266 |
| mcpgateway/toolops/utils/db\_util.py                                           |       34 |        0 |        4 |        1 |     97% |  78->exit |
| mcpgateway/toolops/utils/format\_conversion.py                                 |       23 |        0 |        6 |        0 |    100% |           |
| mcpgateway/toolops/utils/llm\_util.py                                          |       85 |       10 |       14 |        2 |     88% |176-182, 203-207 |
| mcpgateway/tools/builder/cli.py                                                |      114 |        1 |       14 |        2 |     98% |105, 151->exit |
| mcpgateway/tools/builder/factory.py                                            |       31 |        1 |        8 |        2 |     92% |119->122, 134 |
| mcpgateway/tools/builder/pipeline.py                                           |       39 |        2 |        6 |        2 |     91% |  184, 205 |
| mcpgateway/tools/builder/schema.py                                             |       85 |        0 |        6 |        0 |    100% |           |
| mcpgateway/tools/cli.py                                                        |        8 |        1 |        0 |        0 |     88% |        53 |
| mcpgateway/translate.py                                                        |      806 |      126 |      292 |       68 |     80% |146-147, 170-174, 411->410, 474-476, 478->485, 734->739, 777->780, 785-791, 797->exit, 834->841, 1131, 1193, 1204, 1231, 1235, 1242, 1250-1262, 1290->exit, 1297-1299, 1318-1327, 1340-1345, 1359->exit, 1419, 1450, 1484, 1487->1493, 1512-1524, 1542-1545, 1630, 1634, 1641, 1660->1632, 1666-1667, 1682->exit, 1690-1692, 1699->1698, 1701->1698, 1713-1718, 1732->exit, 1756->exit, 1765, 1772->1771, 1774->1771, 1785-1790, 1848->1852, 1852->1973, 1865, 1869->1879, 1874->1879, 1895->1898, 1906, 1908->1899, 1915->exit, 1942->1954, 1947->1954, 1955-1957, 1968, 1980, 2040, 2046, 2055, 2058-2059, 2064-2066, 2069->2052, 2070->2069, 2075, 2081, 2097-2103, 2123, 2126->2131, 2145->2147, 2165-2166, 2172-2173, 2175, 2196->exit, 2205, 2222->2226, 2375-2381, 2387-2397, 2415->2419, 2443-2444 |
| mcpgateway/translate\_grpc.py                                                  |      224 |       13 |       68 |        4 |     94% |27-36, 133->132, 166->165, 175-177, 181->180, 430, 442 |
| mcpgateway/translate\_header\_utils.py                                         |       76 |        6 |       26 |        4 |     90% |65, 159, 165, 341-343 |
| mcpgateway/transports/base.py                                                  |       13 |        0 |        0 |        0 |    100% |           |
| mcpgateway/transports/redis\_event\_store.py                                   |       78 |       13 |       18 |        7 |     79% |26, 179, 219-220, 228-229, 234, 242->250, 245-246, 248, 255, 258-259 |
| mcpgateway/transports/sse\_transport.py                                        |      252 |       26 |       68 |       12 |     87% |103->105, 124, 167-169, 256->260, 262->exit, 594->600, 735, 741->750, 745->750, 753->816, 771, 780->753, 783-787, 806-814, 820->exit, 828-836 |
| mcpgateway/transports/stdio\_transport.py                                      |       56 |        0 |        8 |        0 |    100% |           |
| mcpgateway/transports/streamablehttp\_transport.py                             |      745 |      294 |      260 |       34 |     56% |298->300, 370, 374, 381, 422-443, 458, 518-519, 532, 534->537, 543-544, 546-623, 660, 675-677, 737-738, 744-745, 789, 791->794, 841, 843->846, 897, 899->902, 906-907, 966, 968->971, 1021, 1023->1026, 1030-1031, 1053, 1106-1111, 1131-1148, 1177-1221, 1258-1259, 1344-1350, 1367-1375, 1381-1464, 1468-1610, 1634-1642, 1656-1669, 1673, 1774->1771, 1776->1771, 1844, 1850-1851, 1862-1864, 1875-1883 |
| mcpgateway/transports/websocket\_transport.py                                  |       81 |        3 |       18 |        2 |     95% |113->116, 143-145, 149 |
| mcpgateway/utils/analyze\_query\_log.py                                        |       97 |        3 |       36 |        2 |     95% |110->109, 194-196 |
| mcpgateway/utils/base\_models.py                                               |        8 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/correlation\_id.py                                            |       38 |        0 |       14 |        0 |    100% |           |
| mcpgateway/utils/create\_jwt\_token.py                                         |       89 |        0 |       30 |        0 |    100% |           |
| mcpgateway/utils/create\_slug.py                                               |       13 |        0 |        2 |        0 |    100% |           |
| mcpgateway/utils/db\_isready.py                                                |       93 |        1 |       20 |        1 |     98% |       360 |
| mcpgateway/utils/display\_name.py                                              |        9 |        0 |        4 |        1 |     92% |    66->70 |
| mcpgateway/utils/error\_formatter.py                                           |       54 |        2 |       32 |        2 |     95% |  313, 315 |
| mcpgateway/utils/generate\_keys.py                                             |       31 |        3 |        0 |        0 |     90% |   146-148 |
| mcpgateway/utils/jwt\_config\_helper.py                                        |       67 |        7 |       24 |        5 |     87% |59, 70-71, 127, 129, 162, 190 |
| mcpgateway/utils/keycloak\_discovery.py                                        |       46 |        5 |        4 |        1 |     88% |123-124, 132-134 |
| mcpgateway/utils/metadata\_capture.py                                          |       55 |        0 |       24 |        0 |    100% |           |
| mcpgateway/utils/metrics\_common.py                                            |        4 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/orjson\_response.py                                           |        7 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/pagination.py                                                 |      174 |       22 |       70 |       13 |     84% |257->261, 263, 347-348, 454->477, 459->466, 462-463, 467->477, 518->530, 606, 612-614, 743-750, 755-762, 785, 792->794 |
| mcpgateway/utils/passthrough\_headers.py                                       |      158 |       41 |       72 |       14 |     73% |223-231, 235->245, 238->245, 241-242, 360-366, 369-377, 381-382, 391->428, 395-396, 406-410, 414-415, 419-420, 426, 526->534, 530-531 |
| mcpgateway/utils/psycopg3\_optimizations.py                                    |      100 |        7 |       34 |        3 |     93% |56-57, 130, 143-145, 266, 269->273 |
| mcpgateway/utils/redis\_client.py                                              |       79 |       10 |       18 |        3 |     87% |48, 79, 83, 128-131, 151, 162-163 |
| mcpgateway/utils/redis\_isready.py                                             |       52 |        0 |       10 |        0 |    100% |           |
| mcpgateway/utils/retry\_manager.py                                             |      124 |        0 |       40 |        1 |     99% |  277->284 |
| mcpgateway/utils/security\_cookies.py                                          |       15 |        0 |        0 |        0 |    100% |           |
| mcpgateway/utils/services\_auth.py                                             |       56 |        0 |       12 |        0 |    100% |           |
| mcpgateway/utils/sqlalchemy\_modifier.py                                       |      120 |       10 |       50 |        3 |     90% |195-206, 257, 337 |
| mcpgateway/utils/ssl\_context\_cache.py                                        |       20 |        1 |        8 |        1 |     93% |        66 |
| mcpgateway/utils/ssl\_key\_manager.py                                          |       46 |        0 |        6 |        0 |    100% |           |
| mcpgateway/utils/sso\_bootstrap.py                                             |       68 |       11 |       28 |        3 |     85% |261-263, 343-347, 353-357 |
| mcpgateway/utils/token\_scoping.py                                             |       30 |        2 |       10 |        0 |     95% |     70-72 |
| mcpgateway/utils/url\_auth.py                                                  |       45 |        0 |       16 |        0 |    100% |           |
| mcpgateway/utils/validate\_signature.py                                        |       71 |        6 |       20 |        4 |     89% |80, 113, 203-205, 289 |
| mcpgateway/utils/verify\_credentials.py                                        |      186 |       44 |       96 |        5 |     76% |391-393, 723->728, 823->826, 876-926, 948-954 |
| mcpgateway/validation/jsonrpc.py                                               |       58 |        0 |       34 |        0 |    100% |           |
| mcpgateway/validation/tags.py                                                  |       72 |        3 |       38 |        3 |     95% |167, 257, 265 |
| mcpgateway/validators.py                                                       |        2 |        0 |        0 |        0 |    100% |           |
| mcpgateway/version.py                                                          |      137 |       16 |       24 |        3 |     87% |84-85, 89-96, 835-840, 845-853 |
| mcpgateway/wrapper.py                                                          |      307 |       59 |      134 |       30 |     76% |101->exit, 139-140, 181, 218, 287-288, 314, 316, 325->324, 347, 349, 358->361, 363, 369, 371->355, 376-385, 389, 414, 431, 441-446, 457, 475, 490, 492, 499, 505->511, 514-517, 538->exit, 541, 544, 628-629, 642->665, 657-659, 668->672, 744, 759-775 |
| **TOTAL**                                                                      | **51236** | **7216** | **15546** | **2511** | **83%** |           |
