// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::extract::Query;
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use chrono::Utc;
use serde_json::json;

use crate::delay::{compute_delay, validate_delay};
use crate::time::parse_timezone;

#[derive(Debug, serde::Deserialize)]
pub(crate) struct RestEchoRequest {
    message: String,
    #[serde(default)]
    delay: Option<u64>,
    #[serde(default)]
    delay_stddev: Option<f64>,
}

#[derive(Debug, serde::Deserialize)]
pub(crate) struct RestTimeQuery {
    #[serde(default)]
    tz: Option<String>,
}

pub(crate) async fn echo_handler(axum::Json(req): axum::Json<RestEchoRequest>) -> Response {
    let delay = match validate_delay(req.delay) {
        Ok(delay) => delay,
        Err(message) => {
            return (
                StatusCode::BAD_REQUEST,
                [(header::CONTENT_TYPE, "application/json")],
                serde_json::to_string(&json!({ "error": message })).unwrap_or_default(),
            )
                .into_response();
        }
    };
    if let Some(ms) = delay
        && ms > 0
    {
        let actual_ms = compute_delay(ms, req.delay_stddev);
        tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
    }
    axum::Json(json!({ "message": req.message })).into_response()
}

pub(crate) async fn time_handler(
    Query(query): Query<RestTimeQuery>,
) -> axum::Json<serde_json::Value> {
    let tz_name = query.tz.as_deref().unwrap_or("UTC");
    let now_utc = Utc::now();

    match parse_timezone(tz_name) {
        Ok(timezone) => axum::Json(json!({
            "time": timezone.format_utc(now_utc),
            "timezone": tz_name
        })),
        Err(e) => axum::Json(json!({
            "error": format!("Invalid timezone '{}': {}", tz_name, e)
        })),
    }
}
