use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::Result;
use csv::{ReaderBuilder, WriterBuilder};
use serde::Serialize;
use serde_json::{Value, json};

use crate::{MeasurementConfig, ScenarioSummary, SuiteMeta};

pub fn write_goose_stats_csv(request_log_path: &Path, csv_prefix: &Path) -> Result<()> {
    if !request_log_path.exists() {
        return Ok(());
    }
    let mut rows = Vec::new();
    let mut reader = ReaderBuilder::new().from_path(request_log_path)?;
    for row in reader.deserialize::<BTreeMap<String, String>>() {
        rows.push(row?);
    }
    let mut groups: BTreeMap<String, Vec<BTreeMap<String, String>>> = BTreeMap::new();
    for row in rows.iter() {
        let name = row
            .get("name")
            .cloned()
            .unwrap_or_else(|| "unknown".to_string());
        groups.entry(name).or_default().push(row.clone());
    }
    let stats_path = PathBuf::from(format!("{}_stats.csv", csv_prefix.display()));
    let mut writer = WriterBuilder::new().from_path(stats_path)?;
    writer.write_record([
        "Name",
        "Request Count",
        "Failure Count",
        "Average Response Time",
        "Min Response Time",
        "Max Response Time",
        "50%",
        "95%",
        "99%",
    ])?;
    let aggregate = aggregate_rows("Aggregated", &rows);
    writer.serialize(&aggregate)?;
    for (name, group) in groups {
        writer.serialize(aggregate_rows(&name, &group))?;
    }
    writer.flush()?;

    let mut by_second: BTreeMap<i64, Vec<BTreeMap<String, String>>> = BTreeMap::new();
    for row in rows.iter() {
        let second = row
            .get("elapsed")
            .and_then(|value| value.parse::<f64>().ok())
            .unwrap_or(0.0) as i64;
        by_second.entry(second).or_default().push(row.clone());
    }
    let history_path = PathBuf::from(format!("{}_stats_history.csv", csv_prefix.display()));
    let mut history = WriterBuilder::new().from_path(history_path)?;
    history.write_record([
        "Timestamp",
        "Requests/s",
        "95%",
        "99%",
        "Total Request Count",
        "Total Failure Count",
        "Total Median Response Time",
        "Total Average Response Time",
    ])?;
    let mut cumulative = Vec::new();
    let mut cumulative_failures = 0u64;
    for (second, batch) in by_second {
        cumulative.extend(batch.clone());
        cumulative_failures += batch
            .iter()
            .filter(|row| {
                row.get("success")
                    .map(|value| value != "true")
                    .unwrap_or(false)
            })
            .count() as u64;
        let response_times = batch.iter().map(response_time).collect::<Vec<_>>();
        let cumulative_times = cumulative.iter().map(response_time).collect::<Vec<_>>();
        history.write_record(&[
            second.to_string(),
            batch.len().to_string(),
            percentile(&response_times, 0.95).to_string(),
            percentile(&response_times, 0.99).to_string(),
            cumulative.len().to_string(),
            cumulative_failures.to_string(),
            percentile(&cumulative_times, 0.50).to_string(),
            average(&cumulative_times).to_string(),
        ])?;
    }
    history.flush()?;
    Ok(())
}

#[derive(Serialize)]
struct GooseStatsRow {
    #[serde(rename = "Name")]
    name: String,
    #[serde(rename = "Request Count")]
    request_count: String,
    #[serde(rename = "Failure Count")]
    failure_count: String,
    #[serde(rename = "Average Response Time")]
    average_response_time: String,
    #[serde(rename = "Min Response Time")]
    min_response_time: String,
    #[serde(rename = "Max Response Time")]
    max_response_time: String,
    #[serde(rename = "50%")]
    p50: String,
    #[serde(rename = "95%")]
    p95: String,
    #[serde(rename = "99%")]
    p99: String,
}

fn aggregate_rows(name: &str, rows: &[BTreeMap<String, String>]) -> GooseStatsRow {
    let response_times = rows.iter().map(response_time).collect::<Vec<_>>();
    let failures = rows
        .iter()
        .filter(|row| {
            row.get("success")
                .map(|value| value != "true")
                .unwrap_or(false)
        })
        .count();
    GooseStatsRow {
        name: name.to_string(),
        request_count: rows.len().to_string(),
        failure_count: failures.to_string(),
        average_response_time: average(&response_times).to_string(),
        min_response_time: response_times
            .iter()
            .cloned()
            .fold(0.0_f64, f64::min)
            .to_string(),
        max_response_time: response_times
            .iter()
            .cloned()
            .fold(0.0_f64, f64::max)
            .to_string(),
        p50: percentile(&response_times, 0.50).to_string(),
        p95: percentile(&response_times, 0.95).to_string(),
        p99: percentile(&response_times, 0.99).to_string(),
    }
}

fn response_time(row: &BTreeMap<String, String>) -> f64 {
    row.get("response_time")
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(0.0)
}

fn average(values: &[f64]) -> f64 {
    if values.is_empty() {
        0.0
    } else {
        values.iter().sum::<f64>() / values.len() as f64
    }
}

fn percentile(values: &[f64], pct: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
    let index = ((sorted.len().saturating_sub(1)) as f64 * pct).round() as usize;
    sorted[index.min(sorted.len().saturating_sub(1))]
}

pub fn collect_endpoint_metrics(
    csv_prefix: &Path,
    measurement: &MeasurementConfig,
) -> Result<Value> {
    let path = PathBuf::from(format!("{}_stats.csv", csv_prefix.display()));
    if !path.exists() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats CSV not found"}));
    }
    let mut reader = ReaderBuilder::new().from_path(path)?;
    let rows = reader
        .deserialize::<BTreeMap<String, String>>()
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let aggregate = rows
        .iter()
        .find(|row| {
            row.get("Name")
                .map(|value| value == "Aggregated")
                .unwrap_or(false)
        })
        .cloned()
        .unwrap_or_default();
    let endpoints = rows
        .into_iter()
        .filter(|row| {
            row.get("Name")
                .map(|value| value != "Aggregated")
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    let window = measurement_window_summary(csv_prefix, measurement)?;
    Ok(json!({
        "status":"ok",
        "aggregated": aggregate,
        "measurement_window": window,
        "endpoints": endpoints,
    }))
}

fn measurement_window_summary(csv_prefix: &Path, measurement: &MeasurementConfig) -> Result<Value> {
    let path = PathBuf::from(format!("{}_stats_history.csv", csv_prefix.display()));
    if !path.exists() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats history CSV not found"}));
    }
    let mut reader = ReaderBuilder::new().from_path(path)?;
    let rows = reader
        .deserialize::<BTreeMap<String, String>>()
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if rows.is_empty() {
        return Ok(json!({"status":"unavailable","reason":"Goose stats history CSV was empty"}));
    }
    let warmup = measurement.warmup_seconds as i64;
    let cooldown = measurement.cooldown_seconds as i64;
    let max_timestamp = rows
        .iter()
        .filter_map(|row| {
            row.get("Timestamp")
                .and_then(|value| value.parse::<i64>().ok())
        })
        .max()
        .unwrap_or(0);
    let window = rows
        .iter()
        .filter(|row| {
            let ts = row
                .get("Timestamp")
                .and_then(|value| value.parse::<i64>().ok())
                .unwrap_or(0);
            ts >= warmup && ts <= (max_timestamp - cooldown)
        })
        .cloned()
        .collect::<Vec<_>>();
    if window.is_empty() {
        return Ok(
            json!({"status":"unavailable","reason":"Measurement window did not overlap with Goose stats history"}),
        );
    }
    Ok(json!({
        "status":"ok",
        "source":"goose_stats_history_window",
        "warmup_seconds": measurement.warmup_seconds,
        "measure_seconds": measurement.measure_seconds,
        "cooldown_seconds": measurement.cooldown_seconds,
        "samples": window.len(),
        "aggregated": {
            "Request Count": window.last().and_then(|row| row.get("Total Request Count")).cloned().unwrap_or_else(|| "0".to_string()),
            "Failure Count": window.last().and_then(|row| row.get("Total Failure Count")).cloned().unwrap_or_else(|| "0".to_string()),
            "Requests/s": average(&window.iter().filter_map(|row| row.get("Requests/s").and_then(|value| value.parse::<f64>().ok())).collect::<Vec<_>>()),
            "95%": window.iter().filter_map(|row| row.get("95%").and_then(|value| value.parse::<f64>().ok())).fold(0.0_f64, f64::max),
            "99%": window.iter().filter_map(|row| row.get("99%").and_then(|value| value.parse::<f64>().ok())).fold(0.0_f64, f64::max),
        }
    }))
}

pub fn build_run_summary(suite: &SuiteMeta, summaries: &[ScenarioSummary]) -> Value {
    json!({
        "suite_name": suite.name,
        "scenario_count": summaries.len(),
        "scenarios": summaries.iter().map(|summary| json!({
            "scenario": summary.scenario,
            "status": summary.status,
            "runtime": summary.runtime.http_server,
            "auth_mode": summary.setup.auth_mode,
            "topology_mode": summary.topology.mode,
            "gateway_count": summary.topology.gateway_count,
            "ingress_enabled": summary.topology.ingress_enabled,
            "shared_services": summary.topology.shared_services,
            "gateway_override_count": summary.topology.gateway_override.len(),
        })).collect::<Vec<_>>()
    })
}

pub fn build_comparison_report(summaries: &[ScenarioSummary]) -> Value {
    let mut comparisons = Vec::new();
    for pair in summaries.windows(2) {
        let left = &pair[0];
        let right = &pair[1];
        let left_rps = metric_value(&left.endpoint_metrics, "Requests/s");
        let right_rps = metric_value(&right.endpoint_metrics, "Requests/s");
        let left_p95 = metric_value(&left.endpoint_metrics, "95%");
        let right_p95 = metric_value(&right.endpoint_metrics, "95%");
        comparisons.push(json!({
            "left": left.scenario,
            "right": right.scenario,
            "rps_delta": right_rps - left_rps,
            "p95_delta": right_p95 - left_p95,
            "changed_dimensions": changed_dimensions(left, right),
        }));
    }
    json!({ "comparisons": comparisons })
}

fn metric_value(metrics: &Value, key: &str) -> f64 {
    metrics
        .get("measurement_window")
        .and_then(|window| window.get("aggregated"))
        .and_then(|aggregated| aggregated.get(key))
        .and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str().and_then(|inner| inner.parse::<f64>().ok()))
        })
        .unwrap_or(0.0)
}

fn changed_dimensions(left: &ScenarioSummary, right: &ScenarioSummary) -> Vec<String> {
    let mut dimensions = Vec::new();
    if left.runtime.http_server != right.runtime.http_server {
        dimensions.push("runtime.http_server".to_string());
    }
    if left.setup.auth_mode != right.setup.auth_mode {
        dimensions.push("setup.auth_mode".to_string());
    }
    if left.load.driver != right.load.driver {
        dimensions.push("load.driver".to_string());
    }
    if left.topology.mode != right.topology.mode {
        dimensions.push("topology.mode".to_string());
    }
    if left.topology.gateway_count != right.topology.gateway_count {
        dimensions.push("topology.gateway_count".to_string());
    }
    if left.topology.ingress_enabled != right.topology.ingress_enabled {
        dimensions.push("topology.ingress_enabled".to_string());
    }
    if left.topology.shared_services != right.topology.shared_services {
        dimensions.push("topology.shared_services".to_string());
    }
    if left.topology.gateway_override.len() != right.topology.gateway_override.len() {
        dimensions.push("topology.gateway_override".to_string());
    }
    dimensions
}

pub fn regenerate_reports(run_dir: &Path) -> Result<PathBuf> {
    let mut summaries = Vec::new();
    let scenarios_dir = run_dir.join("scenarios");
    for entry in fs::read_dir(&scenarios_dir)? {
        let path = entry?.path().join("summary.json");
        if path.exists() {
            let raw = fs::read_to_string(&path)?;
            summaries.push(serde_json::from_str::<ScenarioSummary>(&raw)?);
        }
    }
    let suite = SuiteMeta {
        name: run_dir
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("benchmark-run")
            .to_string(),
        ..SuiteMeta::default()
    };
    let run_summary = build_run_summary(&suite, &summaries);
    write_json(&run_dir.join("run_summary.json"), &run_summary)?;
    write_text(
        &run_dir.join("run_summary.md"),
        &render_run_summary_markdown(&run_summary),
    )?;
    let comparison = build_comparison_report(&summaries);
    write_json(
        &run_dir.join("scenario_comparison_report.json"),
        &comparison,
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.md"),
        &render_comparison_markdown(&comparison),
    )?;
    write_text(
        &run_dir.join("scenario_comparison_report.html"),
        &render_comparison_html(&comparison),
    )?;
    Ok(run_dir.to_path_buf())
}

pub(crate) fn render_run_summary_markdown(summary: &Value) -> String {
    let mut lines = vec![
        "# Benchmark Run Summary".to_string(),
        String::new(),
        format!(
            "- Suite: `{}`",
            summary
                .get("suite_name")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
        ),
        format!(
            "- Scenario count: `{}`",
            summary
                .get("scenario_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
        String::new(),
    ];
    if let Some(items) = summary.get("scenarios").and_then(Value::as_array) {
        for item in items {
            lines.push(format!(
                "- `{}`: status=`{}` runtime=`{}` auth=`{}`", // pragma: allowlist secret
                item.get("scenario")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("runtime")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown"),
                item.get("auth_mode")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            ));
        }
    }
    lines.join("\n")
}

pub(crate) fn render_comparison_markdown(report: &Value) -> String {
    let mut lines = vec!["# Scenario Comparison Report".to_string(), String::new()];
    if let Some(items) = report.get("comparisons").and_then(Value::as_array) {
        for item in items {
            lines.push(format!(
                "- `{}` vs `{}`: rps_delta=`{:.2}` p95_delta=`{:.2}`",
                item.get("left").and_then(Value::as_str).unwrap_or("left"),
                item.get("right").and_then(Value::as_str).unwrap_or("right"),
                item.get("rps_delta").and_then(Value::as_f64).unwrap_or(0.0),
                item.get("p95_delta").and_then(Value::as_f64).unwrap_or(0.0)
            ));
        }
    }
    lines.join("\n")
}

pub(crate) fn render_comparison_html(report: &Value) -> String {
    let mut rows = String::new();
    if let Some(items) = report.get("comparisons").and_then(Value::as_array) {
        for item in items {
            rows.push_str(&format!(
                "<tr><td>{}</td><td>{}</td><td>{:.2}</td><td>{:.2}</td></tr>",
                html_escape(item.get("left").and_then(Value::as_str).unwrap_or("left")),
                html_escape(item.get("right").and_then(Value::as_str).unwrap_or("right")),
                item.get("rps_delta").and_then(Value::as_f64).unwrap_or(0.0),
                item.get("p95_delta").and_then(Value::as_f64).unwrap_or(0.0),
            ));
        }
    }
    format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Scenario Comparison Report</title></head><body><h1>Scenario Comparison Report</h1><table border=\"1\"><thead><tr><th>Left</th><th>Right</th><th>RPS Delta</th><th>P95 Delta</th></tr></thead><tbody>{rows}</tbody></table></body></html>"
    )
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

pub(crate) fn write_json<T: Serialize>(path: &Path, payload: &T) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(payload)?)?;
    Ok(())
}

pub(crate) fn write_text(path: &Path, payload: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, payload)?;
    Ok(())
}

pub(crate) fn slug(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() {
                ch.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .split('-')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}
