pub(crate) fn generator_explanation(key: &str) -> &'static str {
    match key {
        "file_stem" => "Sets the filename stem used when the generator saves a scenario TOML.",
        "template_kind" => "Chooses which starter benchmark shape the generator should prefill.",
        "suite_name" => "Sets the suite title stored in `[suite].name`.",
        "suite_description" => {
            "Sets the operator-facing explanation stored in `[suite].description`."
        }
        "output_root" => "Sets the root directory where this suite writes reports and artifacts.",
        "continue_on_failure" => {
            "Controls whether the suite continues running after one scenario fails."
        }
        "save_intermediate_artifacts" => {
            "Controls whether intermediate raw outputs are kept between stages."
        }
        "flamegraph_enabled" => {
            "Marks the suite as able to produce flamegraph-style profiling artifacts."
        }
        "baseline_run" => {
            "Points the suite at a previously saved run summary that should act as the comparison baseline."
        }
        "baseline_rps_drop_pct" => {
            "Sets the allowed throughput drop threshold when comparing the current run against the baseline run."
        }
        "baseline_p95_regression_pct" => {
            "Sets the allowed p95 latency regression threshold when comparing the current run against the baseline run."
        }
        "baseline_failure_increase" => {
            "Sets the allowed increase in failure rate when comparing the current run against the baseline run."
        }
        "scenario_name" => "Sets the scenario name stored in the first `[[scenario]]` entry.",
        "scenario_description" => {
            "Sets the scenario description stored in the first `[[scenario]]` entry."
        }
        "scenario_type" => "Sets the scenario classification label used in reports.",
        "target_kind" => "Defines whether the benchmark is aimed at gateway or agent behavior.",
        "auth_mode" => "Defines which authentication mode the generated scenario expects.",
        "plugins_enabled" => "Defines whether plugin-aware setup is enabled by default.",
        "expected_mcp_runtime" => "Defines the MCP runtime expectation stored in scenario setup.",
        "expected_mcp_runtime_mode" => {
            "Defines the expected MCP runtime mode when MCP runtime assertions are active."
        }
        "expected_a2a_runtime" => "Defines the A2A runtime expectation stored in scenario setup.",
        "rust_plugins" => {
            "Defines whether the benchmark image should include Rust plugin artifacts."
        }
        "profiling_image" => {
            "Defines whether the benchmark image should contain profiling tooling."
        }
        "container_file" => "Defines which Containerfile the benchmark image build should use.",
        "image_name" => "Defines the container image repository name for the benchmark image.",
        "image_tag" => "Defines the container image tag used for this generated suite.",
        "rebuild_policy" => "Defines when the runner is allowed to rebuild the benchmark image.",
        "build_args" => "Defines additional build arguments passed into the benchmark image build.",
        "http_server" => {
            "Defines which application server implementation the benchmark image should run."
        }
        "runtime_host" => {
            "Defines which host address the app binds to inside the benchmark container."
        }
        "transport_type" => {
            "Defines which gateway transport path the benchmark traffic should exercise."
        }
        "topology_mode" => "Defines whether the scenario uses one gateway or a gateway fleet.",
        "gateway_count" => "Defines how many gateway instances the runner should synthesize.",
        "ingress_enabled" => "Defines whether an ingress service fronts the gateway nodes.",
        "ingress_service" => "Defines which compose ingress service receives benchmark traffic.",
        "shared_services" => "Defines which shared backing services stay enabled for the topology.",
        "gateway_base_service" => {
            "Defines which compose service acts as the source template for gateway nodes."
        }
        "gateway_name_prefix" => "Defines the generated service-name prefix for gateway nodes.",
        "gateway_overrides" => {
            "Defines per-node override blocks for environment, ports, or labels."
        }
        "gunicorn_workers" => "Defines how many Gunicorn worker processes should be launched.",
        "gunicorn_timeout" => "Defines Gunicorn's timeout for slow requests and worker startup.",
        "gunicorn_graceful_timeout" => "Defines Gunicorn's graceful shutdown timeout.",
        "gunicorn_keep_alive" => "Defines how long Gunicorn keeps idle connections open.",
        "gunicorn_max_requests" => "Defines Gunicorn's worker recycling request limit.",
        "gunicorn_max_requests_jitter" => {
            "Defines the jitter applied to Gunicorn worker recycling."
        }
        "gunicorn_backlog" => "Defines the Gunicorn listen backlog size.",
        "gunicorn_preload_app" => {
            "Defines whether Gunicorn preloads the application before forking."
        }
        "gunicorn_dev_mode" => "Defines whether Gunicorn should use development-friendly behavior.",
        "granian_workers" => "Defines how many Granian worker processes should be launched.",
        "granian_runtime_mode" => "Defines Granian's runtime execution mode.",
        "granian_runtime_threads" => "Defines how many runtime threads each Granian worker uses.",
        "granian_blocking_threads" => "Defines how many blocking helper threads Granian can use.",
        "granian_http" => "Defines which Granian HTTP stack should be used.",
        "granian_loop" => "Defines which event loop implementation Granian should use.",
        "granian_task_impl" => "Defines which async task runtime Granian should use internally.",
        "granian_http1_pipeline_flush" => {
            "Defines whether Granian flushes pipelined HTTP/1 responses aggressively."
        }
        "granian_http1_buffer_size" => "Defines the Granian HTTP/1 input buffer size.",
        "granian_backlog" => "Defines the Granian listen backlog size.",
        "granian_backpressure" => "Defines Granian's in-flight backpressure threshold.",
        "granian_respawn_failed" => {
            "Defines whether failed Granian workers are restarted automatically."
        }
        "granian_workers_lifetime" => "Defines a maximum lifetime for Granian workers.",
        "granian_workers_max_rss" => "Defines an RSS threshold for Granian worker recycling.",
        "granian_dev_mode" => "Defines whether Granian should use development-friendly behavior.",
        "granian_log_level" => "Defines Granian's server log level.",
        "uvicorn_workers" => "Defines how many Uvicorn worker processes should be launched.",
        "uvicorn_loop" => "Defines which event loop implementation Uvicorn should use.",
        "uvicorn_http" => "Defines which HTTP parser Uvicorn should use.",
        "uvicorn_backlog" => "Defines the Uvicorn listen backlog size.",
        "uvicorn_timeout_keep_alive" => "Defines Uvicorn's keep-alive timeout.",
        "uvicorn_limit_max_requests" => "Defines Uvicorn's worker recycling request limit.",
        "uvicorn_log_level" => "Defines Uvicorn's server log level.",
        "uvicorn_dev_mode" => "Defines whether Uvicorn should use development-friendly behavior.",
        "trust_proxy_auth" => {
            "Defines whether proxy-provided auth headers are trusted by the gateway."
        }
        "disable_access_log" => {
            "Defines whether request access logging is disabled during the run."
        }
        "templates_auto_reload" => {
            "Defines whether templates auto-reload during the benchmark run."
        }
        "structured_logging_database_enabled" => {
            "Defines whether structured database logging is enabled."
        }
        "sqlalchemy_echo" => "Defines whether SQLAlchemy emits SQL statements to logs.",
        "gateway_log_level" => "Defines the gateway application's log verbosity.",
        "gateway_environment" => {
            "Defines extra environment variables injected into the gateway container."
        }
        "target_service" => "Defines which compose service receives benchmark traffic.",
        "driver" => "Defines which Rust benchmark driver binary is invoked for load generation.",
        "headless" => "Defines whether the load driver should minimize interactive output.",
        "only_summary" => {
            "Defines whether the load driver should prefer summary output over verbose logs."
        }
        "html_report" => "Defines whether the run should emit an HTML report artifact.",
        "users" => "Defines the target number of concurrent simulated users.",
        "spawn_rate" => "Defines how quickly those simulated users are started.",
        "run_time" => "Defines the total wall-clock duration of the benchmark run.",
        "request_count" => "Defines an explicit request-count stop condition for the run.",
        "load_host" => "Defines an explicit host URL override for the load driver.",
        "seed" => "Defines the random seed used when workload selection is randomized.",
        "tags" => "Defines which tagged request-catalog entries should stay eligible.",
        "exclude_tags" => "Defines which tagged request-catalog entries should be excluded.",
        "load_extra_args" => "Defines raw CLI flags appended to the load driver invocation.",
        "load_env" => "Defines extra environment variables passed to the load driver.",
        "workload_selection" => "Defines how workload endpoints are selected or mixed.",
        "fallback_endpoint" => "Defines the endpoint used when no other workload target is chosen.",
        "workload_endpoints" => {
            "Defines explicit endpoint weights and enablement for the workload mix."
        }
        "warmup_seconds" => "Defines how long the suite warms up before measuring.",
        "measure_seconds" => "Defines how long the primary metrics window lasts.",
        "profile_seconds" => "Defines how long the dedicated profiling window lasts.",
        "cooldown_seconds" => "Defines how long the suite cools down after measurement ends.",
        "enabled_groups" => "Defines which request-catalog groups are explicitly kept.",
        "disabled_groups" => "Defines which request-catalog groups are explicitly removed.",
        "enabled_endpoints" => "Defines which request-catalog endpoints are explicitly kept.",
        "disabled_endpoints" => "Defines which request-catalog endpoints are explicitly removed.",
        "enabled_tags" => "Defines which request-catalog tags are explicitly kept.",
        "disabled_tags" => "Defines which request-catalog tags are explicitly removed.",
        "include_admin_endpoints" => {
            "Defines whether admin endpoints remain eligible in request selection."
        }
        "include_mcp_endpoints" => {
            "Defines whether MCP endpoints remain eligible in request selection."
        }
        "include_resource_endpoints" => {
            "Defines whether resource endpoints remain eligible in request selection."
        }
        "include_prompt_endpoints" => {
            "Defines whether prompt endpoints remain eligible in request selection."
        }
        "include_tool_endpoints" => {
            "Defines whether tool endpoints remain eligible in request selection."
        }
        "profiling_enabled" => {
            "Defines whether profiling behavior is active for the generated suite."
        }
        "profiling_tools" => "Defines which profiling tools the suite should request.",
        "profiling_duration_seconds" => "Defines how long profiling should run when enabled.",
        "profiling_required" => {
            "Defines whether missing profiling artifacts should fail the scenario."
        }
        "retry_enabled" => "Defines whether failed scenarios should be retried automatically.",
        "max_attempts" => "Defines the maximum number of attempts allowed for a scenario.",
        "capture_logs" => "Defines whether logs are captured into benchmark artifacts.",
        "save_raw_results" => "Defines whether raw result files are preserved after a run.",
        "reuse_stack" => "Defines whether scenarios are allowed to reuse the same running stack.",
        "defaults_plugins_snippet" => {
            "Defines a raw plugin configuration snippet under the defaults block."
        }
        "scenario_setup_snippet" => "Defines a raw setup override for the generated scenario.",
        "scenario_build_snippet" => "Defines a raw build override for the generated scenario.",
        "scenario_runtime_snippet" => "Defines a raw runtime override for the generated scenario.",
        "scenario_topology_snippet" => {
            "Defines a raw topology override for the generated scenario."
        }
        "scenario_gateway_snippet" => "Defines a raw gateway override for the generated scenario.",
        "scenario_load_snippet" => "Defines a raw load override for the generated scenario.",
        "scenario_measurement_snippet" => {
            "Defines a raw measurement override for the generated scenario."
        }
        "scenario_requests_snippet" => {
            "Defines a raw request-selection override for the generated scenario."
        }
        "scenario_profiling_snippet" => {
            "Defines a raw profiling override for the generated scenario."
        }
        "scenario_execution_snippet" => {
            "Defines a raw execution override for the generated scenario."
        }
        "scenario_plugins_snippet" => "Defines a raw plugin override for the generated scenario.",
        _ => "Defines a generator field.",
    }
}

pub(crate) fn generator_change_reason(key: &str) -> &'static str {
    match key {
        "file_stem" => "Changing it changes which scenario file is created or overwritten.",
        "template_kind" => {
            "Changing it swaps in a different preset workload shape and default values."
        }
        "suite_name" => "Changing it changes the suite title shown in metadata and reports.",
        "suite_description" => {
            "Changing it changes the explanation operators read in the console and TOML."
        }
        "output_root" => "Changing it moves where reports and artifacts are written.",
        "continue_on_failure" => {
            "Changing it changes whether later scenarios still run after an earlier failure."
        }
        "save_intermediate_artifacts" => {
            "Changing it changes whether transient artifacts are preserved."
        }
        "flamegraph_enabled" => {
            "Changing it changes whether flamegraph-oriented suite behavior is expected."
        }
        "baseline_run" => {
            "Changing it points the suite at a different saved run to treat as the benchmark baseline."
        }
        "baseline_rps_drop_pct" => {
            "Changing it makes the suite more or less strict about tolerated throughput loss."
        }
        "baseline_p95_regression_pct" => {
            "Changing it makes the suite more or less strict about tolerated p95 latency regression."
        }
        "baseline_failure_increase" => {
            "Changing it makes the suite more or less strict about tolerated failure-rate increase."
        }
        "scenario_name" => "Changing it renames the generated scenario in reports and logs.",
        "scenario_description" => "Changing it changes how the scenario is explained to operators.",
        "scenario_type" => "Changing it changes how the scenario is categorized downstream.",
        "target_kind" => {
            "Changing it changes whether the generated scenario targets gateway or agent behavior."
        }
        "auth_mode" => "Changing it changes which auth path the scenario is configured to use.",
        "plugins_enabled" => {
            "Changing it changes whether plugin-specific fields and setup matter in the template."
        }
        "expected_mcp_runtime" => {
            "Changing it changes the MCP runtime assertion recorded in the scenario."
        }
        "expected_mcp_runtime_mode" => "Changing it changes the asserted MCP runtime mode.",
        "expected_a2a_runtime" => {
            "Changing it changes the A2A runtime assertion recorded in the scenario."
        }
        "rust_plugins" => {
            "Changing it changes whether Rust plugin artifacts are built into the benchmark image."
        }
        "profiling_image" => {
            "Changing it changes whether profiling tooling is installed into the benchmark image."
        }
        "container_file" => "Changing it changes which image definition file the build uses.",
        "image_name" => "Changing it changes the image repository name used during build and run.",
        "image_tag" => "Changing it changes which benchmark image tag is built or reused.",
        "rebuild_policy" => "Changing it changes when the runner rebuilds the benchmark image.",
        "build_args" => {
            "Changing it changes the build-time feature flags or values passed into the image build."
        }
        "http_server" => "Changing it switches the server implementation under the same workload.",
        "runtime_host" => {
            "Changing it changes which interface the app binds to inside the container."
        }
        "transport_type" => {
            "Changing it changes which gateway transport path the load test exercises."
        }
        "topology_mode" => {
            "Changing it changes whether the run is single-node or ingress-balanced across multiple gateway nodes."
        }
        "gateway_count" => "Changing it changes how many gateway containers the runner starts.",
        "ingress_enabled" => {
            "Changing it changes whether benchmark traffic goes through an ingress layer."
        }
        "ingress_service" => {
            "Changing it changes which compose service acts as the benchmark ingress point."
        }
        "shared_services" => {
            "Changing it changes which shared database and cache dependencies are present."
        }
        "gateway_base_service" => {
            "Changing it changes which compose definition is cloned into gateway nodes."
        }
        "gateway_name_prefix" => {
            "Changing it changes the generated gateway service names and override targets."
        }
        "gateway_overrides" => {
            "Changing it changes node-specific environment, port, or label overrides in the generated TOML."
        }
        "gunicorn_workers" => "Changing it changes Gunicorn process concurrency.",
        "gunicorn_timeout" => {
            "Changing it changes how long Gunicorn waits before timing out slow work."
        }
        "gunicorn_graceful_timeout" => "Changing it changes Gunicorn shutdown grace periods.",
        "gunicorn_keep_alive" => "Changing it changes Gunicorn keep-alive behavior.",
        "gunicorn_max_requests" => "Changing it changes Gunicorn worker recycling frequency.",
        "gunicorn_max_requests_jitter" => {
            "Changing it changes how staggered Gunicorn worker recycling is."
        }
        "gunicorn_backlog" => {
            "Changing it changes how many pending connections Gunicorn can queue."
        }
        "gunicorn_preload_app" => {
            "Changing it changes whether the app is loaded once before workers fork."
        }
        "gunicorn_dev_mode" => {
            "Changing it changes whether Gunicorn behaves more like development mode."
        }
        "granian_workers" => "Changing it changes Granian process concurrency.",
        "granian_runtime_mode" => "Changing it changes how Granian executes async work.",
        "granian_runtime_threads" => {
            "Changing it changes how many runtime threads each Granian worker gets."
        }
        "granian_blocking_threads" => {
            "Changing it changes how much blocking work Granian can offload."
        }
        "granian_http" => "Changing it changes the Granian HTTP protocol stack.",
        "granian_loop" => "Changing it changes the event loop implementation Granian uses.",
        "granian_task_impl" => "Changing it changes the async runtime Granian uses internally.",
        "granian_http1_pipeline_flush" => "Changing it changes Granian's HTTP/1 flush behavior.",
        "granian_http1_buffer_size" => "Changing it changes Granian's HTTP/1 buffering behavior.",
        "granian_backlog" => "Changing it changes how many pending connections Granian can queue.",
        "granian_backpressure" => "Changing it changes when Granian starts applying backpressure.",
        "granian_respawn_failed" => {
            "Changing it changes whether failed Granian workers come back automatically."
        }
        "granian_workers_lifetime" => {
            "Changing it changes how often Granian workers recycle by age."
        }
        "granian_workers_max_rss" => {
            "Changing it changes when Granian workers recycle for memory growth."
        }
        "granian_dev_mode" => {
            "Changing it changes whether Granian behaves more like development mode."
        }
        "granian_log_level" => "Changing it changes Granian's server log verbosity.",
        "uvicorn_workers" => "Changing it changes Uvicorn process concurrency.",
        "uvicorn_loop" => "Changing it changes the event loop implementation Uvicorn uses.",
        "uvicorn_http" => "Changing it changes the HTTP parser Uvicorn uses.",
        "uvicorn_backlog" => "Changing it changes how many pending connections Uvicorn can queue.",
        "uvicorn_timeout_keep_alive" => "Changing it changes Uvicorn keep-alive behavior.",
        "uvicorn_limit_max_requests" => "Changing it changes Uvicorn worker recycling frequency.",
        "uvicorn_log_level" => "Changing it changes Uvicorn's server log verbosity.",
        "uvicorn_dev_mode" => {
            "Changing it changes whether Uvicorn behaves more like development mode."
        }
        "trust_proxy_auth" => {
            "Changing it changes whether proxy auth headers are accepted as authoritative."
        }
        "disable_access_log" => {
            "Changing it changes whether access logs are emitted during the run."
        }
        "templates_auto_reload" => "Changing it changes whether template files auto-reload.",
        "structured_logging_database_enabled" => {
            "Changing it changes whether structured logs are written to the database."
        }
        "sqlalchemy_echo" => "Changing it changes whether SQL statements appear in logs.",
        "gateway_log_level" => "Changing it changes gateway log volume.",
        "gateway_environment" => {
            "Changing it changes which environment variables are injected into the gateway container."
        }
        "target_service" => "Changing it changes which service the load generator targets.",
        "driver" => "Changing it changes which benchmark driver binary is executed.",
        "headless" => "Changing it changes how interactive the load output is.",
        "only_summary" => "Changing it changes how much output the load run prints.",
        "html_report" => "Changing it changes whether an HTML report is requested.",
        "users" => "Changing it changes target concurrency.",
        "spawn_rate" => "Changing it changes ramp-up speed.",
        "run_time" => "Changing it changes total benchmark duration.",
        "request_count" => "Changing it changes whether the run stops after a fixed request total.",
        "load_host" => "Changing it changes which host URL the load driver calls.",
        "seed" => "Changing it changes the workload randomization sequence.",
        "tags" => "Changing it changes which tagged requests remain active.",
        "exclude_tags" => "Changing it changes which tagged requests are filtered out.",
        "load_extra_args" => "Changing it changes the raw flags appended to the driver command.",
        "load_env" => "Changing it changes the environment passed to the load driver.",
        "workload_selection" => "Changing it changes how request targets are selected or weighted.",
        "fallback_endpoint" => "Changing it changes the default endpoint used by the workload.",
        "workload_endpoints" => "Changing it changes explicit endpoint weighting and enablement.",
        "warmup_seconds" => {
            "Changing it changes how long the run warms up before measurement starts."
        }
        "measure_seconds" => "Changing it changes how long the primary metrics window lasts.",
        "profile_seconds" => "Changing it changes how long profiling stays active.",
        "cooldown_seconds" => "Changing it changes how long the run cools down before teardown.",
        "enabled_groups" => {
            "Changing it changes which request groups are allowed into the workload."
        }
        "disabled_groups" => {
            "Changing it changes which request groups are removed from the workload."
        }
        "enabled_endpoints" => "Changing it changes which endpoints are kept in the workload.",
        "disabled_endpoints" => {
            "Changing it changes which endpoints are removed from the workload."
        }
        "enabled_tags" => "Changing it changes which tagged endpoints remain active.",
        "disabled_tags" => "Changing it changes which tagged endpoints are removed.",
        "include_admin_endpoints" => "Changing it changes whether admin endpoints remain eligible.",
        "include_mcp_endpoints" => "Changing it changes whether MCP endpoints remain eligible.",
        "include_resource_endpoints" => {
            "Changing it changes whether resource endpoints remain eligible."
        }
        "include_prompt_endpoints" => {
            "Changing it changes whether prompt endpoints remain eligible."
        }
        "include_tool_endpoints" => "Changing it changes whether tool endpoints remain eligible.",
        "profiling_enabled" => "Changing it turns profiling behavior on or off.",
        "profiling_tools" => "Changing it changes which profiling tools the suite requests.",
        "profiling_duration_seconds" => "Changing it changes requested profiling duration.",
        "profiling_required" => "Changing it changes whether missing profiles fail the scenario.",
        "retry_enabled" => "Changing it changes whether failed scenarios are retried.",
        "max_attempts" => "Changing it changes how many attempts the runner may make.",
        "capture_logs" => "Changing it changes whether logs are captured into artifacts.",
        "save_raw_results" => "Changing it changes whether raw result files are preserved.",
        "reuse_stack" => "Changing it changes whether scenarios can reuse the same running stack.",
        "defaults_plugins_snippet" => {
            "Changing it changes the raw plugin configuration written into the defaults block."
        }
        "scenario_setup_snippet" => {
            "Changing it changes only the scenario-specific setup override."
        }
        "scenario_build_snippet" => {
            "Changing it changes only the scenario-specific build override."
        }
        "scenario_runtime_snippet" => {
            "Changing it changes only the scenario-specific runtime override."
        }
        "scenario_topology_snippet" => {
            "Changing it changes only the scenario-specific topology override."
        }
        "scenario_gateway_snippet" => {
            "Changing it changes only the scenario-specific gateway override."
        }
        "scenario_load_snippet" => "Changing it changes only the scenario-specific load override.",
        "scenario_measurement_snippet" => {
            "Changing it changes only the scenario-specific measurement override."
        }
        "scenario_requests_snippet" => {
            "Changing it changes only the scenario-specific request-selection override."
        }
        "scenario_profiling_snippet" => {
            "Changing it changes only the scenario-specific profiling override."
        }
        "scenario_execution_snippet" => {
            "Changing it changes only the scenario-specific execution override."
        }
        "scenario_plugins_snippet" => {
            "Changing it changes only the scenario-specific plugin override."
        }
        _ => "Changing it changes the generated benchmark template.",
    }
}
