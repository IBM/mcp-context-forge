pub(crate) mod catalog;
pub(crate) mod compose;
pub(crate) mod reporting;
pub(crate) mod runtime;
pub(crate) mod runtime_orchestration;
pub(crate) mod scenario_loading;

pub(crate) use catalog::{benchmark_request_names, resolve_requests_from_workload};
pub(crate) use compose::{
    run_command_spec, run_flamegraph, start_stack, stop_stack, uses_a2a_fixture,
    uses_fast_time_fixture,
};
pub(crate) use reporting::{
    build_comparison_report, build_run_summary, collect_endpoint_metrics, render_comparison_html,
    render_comparison_markdown, render_run_summary_markdown, slug, write_goose_stats_csv,
    write_json, write_text,
};
pub(crate) use runtime::build_goose_command;
pub(crate) use runtime_orchestration::{
    benchmark_token, ensure_benchmark_image, ensure_nginx_image, run_compose, wait_for_gateway_health,
    wait_for_service, write_compose_override,
};
