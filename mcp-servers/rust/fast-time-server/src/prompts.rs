// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Static MCP prompts, ported from the Go fast-time-server. Shared by the
//! `/mcp` transport ([`crate::server`]) and the legacy SSE shim
//! ([`crate::transports::sse`]).

use chrono::Utc;
use rmcp::ErrorData as McpError;
use rmcp::model::{GetPromptResult, Prompt, PromptArgument, PromptMessage, PromptMessageRole};
use serde_json::{Value, json};

/// All prompt definitions (for `prompts/list`).
pub(crate) fn list() -> Vec<Prompt> {
    vec![
        Prompt::new(
            "compare_timezones",
            Some("Compare current times across multiple time zones"),
            Some(vec![
                arg(
                    "timezones",
                    "Comma-separated list of timezone IDs to compare",
                    true,
                ),
                arg(
                    "reference_time",
                    "Optional reference time (defaults to now)",
                    false,
                ),
            ]),
        ),
        Prompt::new(
            "schedule_meeting",
            Some("Find optimal meeting time across multiple time zones"),
            Some(vec![
                arg(
                    "participants",
                    "Comma-separated list of participant locations/timezones",
                    true,
                ),
                arg("duration", "Meeting duration in minutes", true),
                arg(
                    "preferred_hours",
                    "Preferred time range (e.g., '9 AM - 5 PM')",
                    false,
                ),
                arg(
                    "date_range",
                    "Date range to consider (e.g., 'next 7 days')",
                    false,
                ),
            ]),
        ),
        Prompt::new(
            "convert_time_detailed",
            Some("Convert time with detailed context"),
            Some(vec![
                arg("time", "Time to convert", true),
                arg("from_timezone", "Source timezone", true),
                arg(
                    "to_timezones",
                    "Comma-separated list of target timezones",
                    true,
                ),
                arg(
                    "include_context",
                    "Whether to include contextual information (true/false)",
                    false,
                ),
            ]),
        ),
    ]
}

/// Render a prompt by name with its string arguments (for `prompts/get`).
pub(crate) fn get(name: &str, arguments: &Value) -> Result<GetPromptResult, McpError> {
    match name {
        "compare_timezones" => compare_timezones(arguments),
        "schedule_meeting" => schedule_meeting(arguments),
        "convert_time_detailed" => convert_time_detailed(arguments),
        _ => Err(McpError::invalid_params(
            format!("unknown prompt: {name}"),
            Some(json!({ "prompt": name })),
        )),
    }
}

fn arg(name: &str, description: &str, required: bool) -> PromptArgument {
    PromptArgument::new(name)
        .with_description(description)
        .with_required(required)
}

/// String argument lookup; treats missing and empty as "not provided", matching
/// the Go handlers (which read `req.Params.Arguments[key]` defaulting to "").
fn arg_str<'a>(arguments: &'a Value, key: &str) -> &'a str {
    arguments
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
}

fn split_csv(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(|item| item.trim().to_string())
        .collect()
}

fn user_prompt(description: &str, text: String) -> GetPromptResult {
    let mut result =
        GetPromptResult::new(vec![PromptMessage::new_text(PromptMessageRole::User, text)]);
    result.description = Some(description.to_string());
    result
}

fn compare_timezones(arguments: &Value) -> Result<GetPromptResult, McpError> {
    let timezones = arg_str(arguments, "timezones");
    if timezones.is_empty() {
        return Err(McpError::invalid_params(
            "timezones parameter is required",
            None,
        ));
    }
    let reference_time = arg_str(arguments, "reference_time");
    let base_time = if reference_time.is_empty() {
        Utc::now()
    } else {
        chrono::DateTime::parse_from_rfc3339(reference_time)
            .map(|dt| dt.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now())
    };

    let mut text = String::from("Compare the current time across these time zones:\n");
    for tz in split_csv(timezones) {
        text.push_str(&format!("- {tz}\n"));
    }
    text.push_str(&format!(
        "\nReference time: {}\n\n",
        base_time.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    ));
    text.push_str("Show:\n");
    text.push_str("1. The current time in each timezone\n");
    text.push_str("2. The time difference from the first timezone\n");
    text.push_str("3. Whether it's business hours (9 AM - 5 PM)\n");
    text.push_str("4. The day of the week\n");

    Ok(user_prompt("Time zone comparison analysis", text))
}

fn schedule_meeting(arguments: &Value) -> Result<GetPromptResult, McpError> {
    let participants = arg_str(arguments, "participants");
    if participants.is_empty() {
        return Err(McpError::invalid_params(
            "participants parameter is required",
            None,
        ));
    }
    let duration = non_empty_or(arg_str(arguments, "duration"), "60");
    let preferred_hours = non_empty_or(arg_str(arguments, "preferred_hours"), "9 AM - 5 PM");
    let date_range = non_empty_or(arg_str(arguments, "date_range"), "next 7 days");

    let mut text =
        String::from("Find the best meeting time for participants in these locations:\n");
    for participant in split_csv(participants) {
        text.push_str(&format!("- {participant}\n"));
    }
    text.push_str("\nMeeting details:\n");
    text.push_str(&format!("- Duration: {duration} minutes\n"));
    text.push_str(&format!(
        "- Preferred hours: {preferred_hours} local time for each participant\n"
    ));
    text.push_str(&format!("- Date range: {date_range}\n\n"));
    text.push_str("Consider:\n");
    text.push_str("1. Business hours overlap across all timezones\n");
    text.push_str("2. Avoid very early morning (before 8 AM) or late evening (after 7 PM)\n");
    text.push_str("3. Account for any timezone transitions (DST changes)\n");
    text.push_str("4. Suggest top 3 meeting times with pros/cons for each\n");

    Ok(user_prompt("Meeting scheduler analysis", text))
}

fn convert_time_detailed(arguments: &Value) -> Result<GetPromptResult, McpError> {
    let time = arg_str(arguments, "time");
    let from_tz = arg_str(arguments, "from_timezone");
    let to_tzs = arg_str(arguments, "to_timezones");
    if time.is_empty() || from_tz.is_empty() || to_tzs.is_empty() {
        return Err(McpError::invalid_params(
            "time, from_timezone, and to_timezones are required",
            None,
        ));
    }
    let include_context = non_empty_or(arg_str(arguments, "include_context"), "false");

    let mut text = format!("Convert {time} from {from_tz} to:\n");
    for tz in split_csv(to_tzs) {
        text.push_str(&format!("- {tz}\n"));
    }
    if include_context == "true" {
        text.push_str("\nAlso provide:\n");
        text.push_str("1. Day of week in each timezone\n");
        text.push_str("2. Whether it's a business day\n");
        text.push_str("3. Any relevant holidays or observances\n");
        text.push_str("4. Time until/since this moment (relative to now)\n");
        text.push_str("5. Sunrise/sunset times if significantly different days\n");
    }

    Ok(user_prompt("Detailed time conversion", text))
}

fn non_empty_or<'a>(value: &'a str, default: &'a str) -> &'a str {
    if value.is_empty() { default } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn message_text(result: &GetPromptResult) -> String {
        serde_json::to_value(&result.messages[0].content).unwrap()["text"]
            .as_str()
            .unwrap()
            .to_string()
    }

    #[test]
    fn test_list_exposes_all_prompts() {
        let names: Vec<String> = list().into_iter().map(|p| p.name).collect();
        assert_eq!(
            names,
            [
                "compare_timezones",
                "schedule_meeting",
                "convert_time_detailed"
            ]
        );
    }

    #[test]
    fn test_compare_timezones_renders_csv() {
        let result = get(
            "compare_timezones",
            &json!({ "timezones": "UTC, Asia/Tokyo" }),
        )
        .expect("compare_timezones should render");
        let text = message_text(&result);
        assert!(text.contains("- UTC\n"));
        assert!(text.contains("- Asia/Tokyo\n"));
        assert!(text.contains("The day of the week"));
    }

    #[test]
    fn test_compare_timezones_requires_timezones() {
        let err = get("compare_timezones", &json!({})).expect_err("missing arg should error");
        assert_eq!(err.code, rmcp::model::ErrorCode::INVALID_PARAMS);
    }

    #[test]
    fn test_schedule_meeting_uses_defaults() {
        let result = get("schedule_meeting", &json!({ "participants": "NYC,London" })).unwrap();
        let text = message_text(&result);
        assert!(text.contains("Duration: 60 minutes"));
        assert!(text.contains("Date range: next 7 days"));
    }

    #[test]
    fn test_convert_time_detailed_context_toggle() {
        let with_ctx = get(
            "convert_time_detailed",
            &json!({ "time": "12:00", "from_timezone": "UTC", "to_timezones": "Asia/Tokyo", "include_context": "true" }),
        )
        .unwrap();
        assert!(message_text(&with_ctx).contains("Day of week in each timezone"));

        let without_ctx = get(
            "convert_time_detailed",
            &json!({ "time": "12:00", "from_timezone": "UTC", "to_timezones": "Asia/Tokyo" }),
        )
        .unwrap();
        assert!(!message_text(&without_ctx).contains("Day of week in each timezone"));
    }

    #[test]
    fn test_unknown_prompt_is_invalid_params() {
        let err = get("nope", &json!({})).expect_err("unknown prompt should error");
        assert_eq!(err.code, rmcp::model::ErrorCode::INVALID_PARAMS);
    }
}
