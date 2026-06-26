// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! REST `/api/v1/*` surface, ported from the Go fast-time-server. Complements
//! the MCP transports with plain HTTP access to time operations.
//!
//! Note: the REST resources and prompts intentionally return the same (simpler)
//! payloads as the Go REST handlers, which differ from the richer MCP
//! resource/prompt content in [`crate::resources`] / [`crate::prompts`].

use axum::Router;
use axum::body::Bytes;
use axum::extract::{Path, Query, Request};
use axum::http::{Method, StatusCode, header};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use chrono::{DateTime, NaiveDateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::time::Instant;

use crate::config::APP_NAME;
use crate::time::parse_timezone;

/// All `/api/v1/*` routes.
pub(crate) fn routes() -> Router {
    Router::new()
        .route("/api/v1/time", get(get_time_query))
        .route("/api/v1/time/{*timezone}", get(get_time_path))
        .route("/api/v1/convert", post(convert))
        .route("/api/v1/convert/batch", post(batch_convert))
        .route("/api/v1/timezones", get(list_timezones))
        .route("/api/v1/timezones/{*timezone}", get(timezone_info))
        .route("/api/v1/resources", get(list_resources))
        .route("/api/v1/resources/{*slug}", get(get_resource))
        .route("/api/v1/prompts", get(list_prompts))
        .route("/api/v1/prompts/{name}/execute", post(execute_prompt))
        .route("/api/v1/test/echo", get(test_echo))
        .route("/api/v1/test/validate", post(test_validate))
        .route("/api/v1/test/performance", get(test_performance))
        .route("/api/v1/openapi.json", get(openapi_json))
        .route("/api/v1/docs", get(api_docs))
}

/// CORS middleware mirroring the Go server: permissive headers and a `204`
/// answer to preflight `OPTIONS`. Applied as an outer layer so preflight is
/// answered without authentication.
pub(crate) async fn cors(request: Request, next: Next) -> Response {
    let mut response = if request.method() == Method::OPTIONS {
        StatusCode::NO_CONTENT.into_response()
    } else {
        next.run(request).await
    };
    let headers = response.headers_mut();
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_ORIGIN,
        header::HeaderValue::from_static("*"),
    );
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_METHODS,
        header::HeaderValue::from_static("GET, POST, OPTIONS"),
    );
    headers.insert(
        header::ACCESS_CONTROL_ALLOW_HEADERS,
        header::HeaderValue::from_static("Content-Type, Authorization"),
    );
    headers.insert(
        header::ACCESS_CONTROL_MAX_AGE,
        header::HeaderValue::from_static("3600"),
    );
    response
}

// ---------------------------------------------------------------------------
// time
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct TimeQuery {
    timezone: Option<String>,
}

async fn get_time_query(Query(query): Query<TimeQuery>) -> Response {
    time_response(query.timezone.unwrap_or_default())
}

async fn get_time_path(Path(timezone): Path<String>) -> Response {
    time_response(timezone)
}

fn time_response(timezone: String) -> Response {
    let timezone = if timezone.is_empty() {
        "UTC".to_string()
    } else {
        timezone
    };
    match parse_timezone(&timezone) {
        Ok(zone) => {
            let now = Utc::now();
            json_ok(json!({
                "time": zone.format_utc(now),
                "timezone": timezone,
                "unix": now.timestamp(),
                "utc": now.to_rfc3339_opts(SecondsFormat::Secs, true),
            }))
        }
        Err(_) => bad_request(&format!("Invalid timezone: {timezone}")),
    }
}

// ---------------------------------------------------------------------------
// convert
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct ConvertRequest {
    time: String,
    from_timezone: String,
    to_timezone: String,
}

#[derive(Debug, Deserialize)]
struct BatchConvertRequest {
    #[serde(default)]
    conversions: Vec<ConvertRequest>,
}

async fn convert(body: Bytes) -> Response {
    let Some(req) = parse_body::<ConvertRequest>(&body) else {
        return bad_request("Invalid request body");
    };
    match convert_one(&req) {
        Ok(result) => json_ok(result),
        Err(message) => bad_request(&message),
    }
}

async fn batch_convert(body: Bytes) -> Response {
    let Some(req) = parse_body::<BatchConvertRequest>(&body) else {
        return bad_request("Invalid request body");
    };
    // Skip invalid entries, matching the Go batch handler.
    let results: Vec<Value> = req
        .conversions
        .iter()
        .filter_map(|conversion| convert_one(conversion).ok())
        .collect();
    json_ok(json!({ "results": results }))
}

fn convert_one(req: &ConvertRequest) -> Result<Value, String> {
    let instant =
        parse_instant(&req.time).ok_or_else(|| format!("Invalid time format: {}", req.time))?;
    let from = parse_timezone(&req.from_timezone)
        .map_err(|_| format!("Invalid source timezone: {}", req.from_timezone))?;
    let to = parse_timezone(&req.to_timezone)
        .map_err(|_| format!("Invalid target timezone: {}", req.to_timezone))?;
    Ok(json!({
        "original_time": from.format_utc(instant),
        "from_timezone": req.from_timezone,
        "converted_time": to.format_utc(instant),
        "to_timezone": req.to_timezone,
        "unix": instant.timestamp(),
    }))
}

/// Parse an instant: RFC3339 (offset-aware) or a naive `YYYY-MM-DD HH:MM:SS`
/// treated as UTC, matching Go's `time.Parse` fallbacks.
fn parse_instant(value: &str) -> Option<DateTime<Utc>> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(value) {
        return Some(dt.with_timezone(&Utc));
    }
    NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S")
        .ok()
        .map(|naive| naive.and_utc())
}

// ---------------------------------------------------------------------------
// timezones
// ---------------------------------------------------------------------------

const KNOWN_TIMEZONES: &[&str] = &[
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Toronto",
    "America/Vancouver",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Rome",
    "Europe/Madrid",
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Zurich",
    "Europe/Stockholm",
    "Europe/Oslo",
    "Europe/Copenhagen",
    "Europe/Helsinki",
    "Europe/Moscow",
    "Europe/Istanbul",
    "Europe/Athens",
    "Europe/Warsaw",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Singapore",
    "Asia/Seoul",
    "Asia/Taipei",
    "Asia/Bangkok",
    "Asia/Jakarta",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Tel_Aviv",
    "Asia/Riyadh",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Australia/Brisbane",
    "Australia/Perth",
    "Pacific/Auckland",
    "Pacific/Fiji",
    "Africa/Cairo",
    "Africa/Lagos",
    "Africa/Johannesburg",
    "Africa/Nairobi",
];

#[derive(Debug, Deserialize)]
struct FilterQuery {
    filter: Option<String>,
}

async fn list_timezones(Query(query): Query<FilterQuery>) -> Response {
    let filter = query.filter.unwrap_or_default().to_lowercase();
    let timezones: Vec<&&str> = KNOWN_TIMEZONES
        .iter()
        .filter(|tz| filter.is_empty() || tz.to_lowercase().contains(&filter))
        .collect();
    json_ok(json!({ "timezones": timezones, "count": timezones.len() }))
}

async fn timezone_info(Path(timezone): Path<String>) -> Response {
    if timezone.is_empty() {
        return bad_request("Timezone not specified");
    }
    let zone = match parse_timezone(&timezone) {
        Ok(zone) => zone,
        Err(_) => return bad_request(&format!("Invalid timezone: {timezone}")),
    };
    let now = Utc::now();
    let (offset_secs, is_dst, abbreviation) = zone.zone_details(now);
    json_ok(json!({
        "name": timezone,
        "offset": format!("{:+}:{:02}", offset_secs / 3600, (offset_secs.abs() % 3600) / 60),
        "current_time": zone.format_utc(now),
        "is_dst": is_dst,
        "abbreviation": abbreviation,
    }))
}

// ---------------------------------------------------------------------------
// resources (REST projection — simpler than the MCP resources)
// ---------------------------------------------------------------------------

async fn list_resources() -> Response {
    json_ok(json!({ "resources": rest_resource_list(), "count": 4 }))
}

async fn get_resource(Path(slug): Path<String>) -> Response {
    let data = match slug.as_str() {
        "timezone-info" => rest_timezone_info(),
        "current-world" => rest_current_world(),
        "time-formats" => rest_time_formats(),
        "business-hours" => rest_business_hours(),
        _ => return not_found(&format!("Resource not found: {slug}")),
    };
    json_ok(data)
}

fn rest_resource_list() -> Value {
    json!([
        { "uri": "timezone://info", "name": "Timezone Information", "description": "Comprehensive timezone information including offsets, DST, and major cities", "mime_type": "application/json" },
        { "uri": "time://current/world", "name": "Current World Times", "description": "Current time in major cities around the world", "mime_type": "application/json" },
        { "uri": "time://formats", "name": "Time Formats", "description": "Examples of supported time formats for parsing and display", "mime_type": "application/json" },
        { "uri": "time://business-hours", "name": "Business Hours", "description": "Standard business hours across different regions", "mime_type": "application/json" }
    ])
}

fn rest_timezone_info() -> Value {
    json!({
        "timezones": [
            { "id": "America/New_York", "name": "Eastern Time", "offset": "-05:00", "dst": true, "abbreviation": "EST/EDT", "major_cities": ["New York", "Toronto", "Montreal"], "population": 141000000_i64 },
            { "id": "Europe/London", "name": "Greenwich Mean Time", "offset": "+00:00", "dst": true, "abbreviation": "GMT/BST", "major_cities": ["London", "Dublin", "Lisbon"], "population": 67000000_i64 },
            { "id": "Asia/Tokyo", "name": "Japan Standard Time", "offset": "+09:00", "dst": false, "abbreviation": "JST", "major_cities": ["Tokyo", "Osaka", "Yokohama"], "population": 127000000_i64 }
        ],
        "timezone_groups": {
            "us_timezones": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
            "europe_timezones": ["Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow"],
            "asia_timezones": ["Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai"]
        }
    })
}

fn rest_current_world() -> Value {
    const CITIES: &[(&str, &str)] = &[
        ("New York", "America/New_York"),
        ("Los Angeles", "America/Los_Angeles"),
        ("London", "Europe/London"),
        ("Paris", "Europe/Paris"),
        ("Tokyo", "Asia/Tokyo"),
        ("Sydney", "Australia/Sydney"),
        ("Dubai", "Asia/Dubai"),
    ];
    let now = Utc::now();
    let mut times = serde_json::Map::new();
    for (city, tz) in CITIES {
        if let Ok(zone) = parse_timezone(tz) {
            times.insert(
                (*city).to_string(),
                Value::String(zone.format_local(now, "%Y-%m-%d %H:%M:%S %Z")),
            );
        }
    }
    json!({
        "last_updated": now.to_rfc3339_opts(SecondsFormat::Secs, true),
        "times": Value::Object(times)
    })
}

fn rest_time_formats() -> Value {
    json!({
        "input_formats": [
            "2006-01-02 15:04:05",
            "2006-01-02T15:04:05Z",
            "2006-01-02T15:04:05-07:00",
            "Jan 2, 2006 3:04 PM"
        ],
        "output_formats": {
            "iso8601": "2006-01-02T15:04:05Z07:00",
            "rfc3339": "2006-01-02T15:04:05Z",
            "rfc822": "Mon, 02 Jan 2006 15:04:05 MST"
        }
    })
}

fn rest_business_hours() -> Value {
    json!({
        "regions": {
            "north_america": { "standard_hours": "9:00 AM - 5:00 PM", "lunch_break": "12:00 PM - 1:00 PM", "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] },
            "europe": { "standard_hours": "9:00 AM - 6:00 PM", "lunch_break": "1:00 PM - 2:00 PM", "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] }
        }
    })
}

// ---------------------------------------------------------------------------
// prompts (REST projection — simpler text than the MCP prompts)
// ---------------------------------------------------------------------------

async fn list_prompts() -> Response {
    json_ok(json!({
        "prompts": [
            {
                "name": "compare_timezones",
                "description": "Compare current times across multiple time zones",
                "arguments": [
                    { "name": "timezones", "description": "Comma-separated list of timezone IDs to compare", "required": true },
                    { "name": "reference_time", "description": "Optional reference time (defaults to now)", "required": false }
                ]
            },
            {
                "name": "schedule_meeting",
                "description": "Find optimal meeting time across multiple time zones",
                "arguments": [
                    { "name": "participants", "description": "Comma-separated list of participant locations/timezones", "required": true },
                    { "name": "duration", "description": "Meeting duration in minutes", "required": true },
                    { "name": "preferred_hours", "description": "Preferred time range (e.g., '9 AM - 5 PM')", "required": false },
                    { "name": "date_range", "description": "Date range to consider (e.g., 'next 7 days')", "required": false }
                ]
            },
            {
                "name": "convert_time_detailed",
                "description": "Convert time with detailed context",
                "arguments": [
                    { "name": "time", "description": "Time to convert", "required": true },
                    { "name": "from_timezone", "description": "Source timezone", "required": true },
                    { "name": "to_timezones", "description": "Comma-separated list of target timezones", "required": true },
                    { "name": "include_context", "description": "Whether to include contextual information (true/false)", "required": false }
                ]
            }
        ],
        "count": 3
    }))
}

async fn execute_prompt(Path(name): Path<String>, body: Bytes) -> Response {
    let Some(args) = parse_body::<serde_json::Map<String, Value>>(&body) else {
        return bad_request("Invalid request body");
    };
    let get = |key: &str| args.get(key).and_then(Value::as_str).unwrap_or_default();
    let text = match name.as_str() {
        "compare_timezones" => gen_compare_timezones(get("timezones"), get("reference_time")),
        "schedule_meeting" => gen_schedule_meeting(
            get("participants"),
            get("duration"),
            non_empty(get("preferred_hours"), "9 AM - 5 PM"),
            non_empty(get("date_range"), "next 7 days"),
        ),
        "convert_time_detailed" => gen_convert_detailed(
            get("time"),
            get("from_timezone"),
            get("to_timezones"),
            get("include_context"),
        ),
        _ => return not_found(&format!("Unknown prompt: {name}")),
    };
    json_ok(json!({ "prompt": name, "arguments": args, "text": text }))
}

fn gen_compare_timezones(timezones: &str, reference_time: &str) -> String {
    let mut text = format!("Compare the current time across these time zones: {timezones}\n");
    if !reference_time.is_empty() {
        text.push_str(&format!("Reference time: {reference_time}\n"));
    }
    text.push_str("\nShow:\n");
    text.push_str("1. The current time in each timezone\n");
    text.push_str("2. The time difference from the first timezone\n");
    text.push_str("3. Whether it's business hours (9 AM - 5 PM)\n");
    text.push_str("4. The day of the week\n");
    text
}

fn gen_schedule_meeting(
    participants: &str,
    duration: &str,
    preferred_hours: &str,
    date_range: &str,
) -> String {
    let mut text = format!("Find the best meeting time for participants in: {participants}\n");
    text.push_str("\nMeeting details:\n");
    text.push_str(&format!("- Duration: {duration} minutes\n"));
    text.push_str(&format!(
        "- Preferred hours: {preferred_hours} local time\n"
    ));
    text.push_str(&format!("- Date range: {date_range}\n"));
    text
}

fn gen_convert_detailed(time: &str, from_tz: &str, to_tzs: &str, include_context: &str) -> String {
    let mut text = format!("Convert {time} from {from_tz} to: {to_tzs}\n");
    if include_context == "true" {
        text.push_str("\nAlso provide:\n");
        text.push_str("1. Day of week in each timezone\n");
        text.push_str("2. Whether it's a business day\n");
        text.push_str("3. Time until/since this moment\n");
    }
    text
}

// ---------------------------------------------------------------------------
// test helpers
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct EchoQuery {
    message: Option<String>,
}

async fn test_echo(Query(query): Query<EchoQuery>) -> Response {
    let message = query
        .message
        .filter(|m| !m.is_empty())
        .unwrap_or_else(|| "Hello from fast-time-server!".to_string());
    json_ok(json!({
        "echo": message,
        "timestamp": now_rfc3339(),
        "server": APP_NAME,
    }))
}

async fn test_validate(body: Bytes) -> Response {
    let received: Value = match serde_json::from_slice(&body) {
        Ok(value) => value,
        Err(_) => return bad_request("Invalid JSON body"),
    };
    json_ok(json!({
        "valid": true,
        "received": received,
        "timestamp": now_rfc3339(),
    }))
}

// ---------------------------------------------------------------------------
// documentation
// ---------------------------------------------------------------------------

async fn openapi_json() -> Response {
    json_ok(crate::openapi::spec())
}

async fn api_docs() -> Response {
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        crate::openapi::DOCS_HTML,
    )
        .into_response()
}

async fn test_performance() -> Response {
    let start = Instant::now();
    let test_ops = 1000u64;
    for _ in 0..test_ops {
        let _ = Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true);
    }
    let duration = start.elapsed();
    let seconds = duration.as_secs_f64();
    json_ok(json!({
        "operations": test_ops,
        "duration_ms": duration.as_millis() as u64,
        "duration_ns": duration.as_nanos() as u64,
        "ops_per_second": if seconds > 0.0 { test_ops as f64 / seconds } else { 0.0 },
        "server_time": now_rfc3339(),
    }))
}

// ---------------------------------------------------------------------------
// shared helpers
// ---------------------------------------------------------------------------

fn parse_body<T: DeserializeOwned>(body: &Bytes) -> Option<T> {
    serde_json::from_slice(body).ok()
}

fn json_ok(value: Value) -> Response {
    (StatusCode::OK, axum::Json(value)).into_response()
}

fn json_error(code: StatusCode, message: &str) -> Response {
    let body = json!({
        "error": code.canonical_reason().unwrap_or(""),
        "message": message,
        "code": code.as_u16(),
    });
    (code, axum::Json(body)).into_response()
}

fn bad_request(message: &str) -> Response {
    json_error(StatusCode::BAD_REQUEST, message)
}

fn not_found(message: &str) -> Response {
    json_error(StatusCode::NOT_FOUND, message)
}

fn now_rfc3339() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn non_empty<'a>(value: &'a str, default: &'a str) -> &'a str {
    if value.is_empty() { default } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_instant_rfc3339_and_naive() {
        let rfc = parse_instant("2025-06-21T16:00:00Z").unwrap();
        assert_eq!(rfc.timestamp(), 1750521600);
        let naive = parse_instant("2025-01-10 10:00:00").unwrap();
        assert_eq!(
            naive.to_rfc3339_opts(SecondsFormat::Secs, true),
            "2025-01-10T10:00:00Z"
        );
        assert!(parse_instant("not a time").is_none());
    }

    #[test]
    fn test_convert_one_matches_dst() {
        let result = convert_one(&ConvertRequest {
            time: "2025-06-21T16:00:00Z".into(),
            from_timezone: "UTC".into(),
            to_timezone: "America/New_York".into(),
        })
        .expect("conversion should succeed");
        assert_eq!(result["converted_time"], "2025-06-21T12:00:00-04:00");
        assert_eq!(result["unix"], 1750521600_i64);
    }

    #[test]
    fn test_convert_one_rejects_bad_timezone() {
        let err = convert_one(&ConvertRequest {
            time: "2025-06-21T16:00:00Z".into(),
            from_timezone: "Nope/Zone".into(),
            to_timezone: "UTC".into(),
        })
        .expect_err("bad timezone should error");
        assert!(err.contains("Invalid source timezone"));
    }

    #[test]
    fn test_gen_prompts_text() {
        assert!(
            gen_compare_timezones("UTC,Asia/Tokyo", "")
                .contains("these time zones: UTC,Asia/Tokyo")
        );
        let meeting = gen_schedule_meeting("NYC", "30", "9 AM - 5 PM", "next 7 days");
        assert!(meeting.contains("Duration: 30 minutes"));
        let ctx = gen_convert_detailed("12:00", "UTC", "Asia/Tokyo", "true");
        assert!(ctx.contains("Day of week in each timezone"));
        let no_ctx = gen_convert_detailed("12:00", "UTC", "Asia/Tokyo", "false");
        assert!(!no_ctx.contains("Day of week in each timezone"));
    }

    #[test]
    fn test_known_timezones_filter_count() {
        let asia = KNOWN_TIMEZONES
            .iter()
            .filter(|tz| tz.to_lowercase().contains("asia"))
            .count();
        assert_eq!(asia, 12);
    }
}
