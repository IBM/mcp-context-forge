// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Static MCP resources, ported from the Go fast-time-server. Shared by the
//! `/mcp` transport ([`crate::server`]) and the legacy SSE shim
//! ([`crate::transports::sse`]).

use chrono::Utc;
use rmcp::ErrorData as McpError;
use rmcp::model::{Annotated, RawResource, ReadResourceResult, Resource, ResourceContents};
use serde_json::{Value, json};

use crate::time::parse_timezone;

const MIME_JSON: &str = "application/json";

struct ResourceDef {
    uri: &'static str,
    name: &'static str,
    description: &'static str,
}

const RESOURCES: &[ResourceDef] = &[
    ResourceDef {
        uri: "timezone://info",
        name: "Timezone Information",
        description: "Comprehensive timezone information including offsets, DST, and major cities",
    },
    ResourceDef {
        uri: "time://current/world",
        name: "Current World Times",
        description: "Current time in major cities around the world",
    },
    ResourceDef {
        uri: "time://formats",
        name: "Time Formats",
        description: "Examples of supported time formats for parsing and display",
    },
    ResourceDef {
        uri: "time://business-hours",
        name: "Business Hours",
        description: "Standard business hours across different regions",
    },
];

/// All resource definitions (for `resources/list`).
pub(crate) fn list() -> Vec<Resource> {
    RESOURCES
        .iter()
        .map(|def| {
            let mut raw = RawResource::new(def.uri, def.name);
            raw.description = Some(def.description.to_string());
            raw.mime_type = Some(MIME_JSON.to_string());
            Annotated::new(raw, None)
        })
        .collect()
}

/// Resource contents for `resources/read`.
pub(crate) fn read(uri: &str) -> Result<ReadResourceResult, McpError> {
    let payload = match uri {
        "timezone://info" => timezone_info(),
        "time://current/world" => current_world_times(),
        "time://formats" => time_formats(),
        "time://business-hours" => business_hours(),
        _ => {
            return Err(McpError::resource_not_found(
                format!("unknown resource: {uri}"),
                Some(json!({ "uri": uri })),
            ));
        }
    };
    Ok(ReadResourceResult::new(vec![ResourceContents::text(
        payload.to_string(),
        uri,
    )]))
}

fn timezone_info() -> Value {
    json!({
        "timezones": [
            { "id": "America/New_York", "name": "Eastern Time", "offset": "-05:00", "dst": true, "abbreviation": "EST/EDT", "major_cities": ["New York", "Toronto", "Montreal"], "population": 141000000_i64 },
            { "id": "America/Chicago", "name": "Central Time", "offset": "-06:00", "dst": true, "abbreviation": "CST/CDT", "major_cities": ["Chicago", "Houston", "Mexico City"], "population": 110000000_i64 },
            { "id": "America/Denver", "name": "Mountain Time", "offset": "-07:00", "dst": true, "abbreviation": "MST/MDT", "major_cities": ["Denver", "Phoenix", "Calgary"], "population": 35000000_i64 },
            { "id": "America/Los_Angeles", "name": "Pacific Time", "offset": "-08:00", "dst": true, "abbreviation": "PST/PDT", "major_cities": ["Los Angeles", "San Francisco", "Seattle"], "population": 53000000_i64 },
            { "id": "Europe/London", "name": "Greenwich Mean Time", "offset": "+00:00", "dst": true, "abbreviation": "GMT/BST", "major_cities": ["London", "Dublin", "Lisbon"], "population": 67000000_i64 },
            { "id": "Europe/Paris", "name": "Central European Time", "offset": "+01:00", "dst": true, "abbreviation": "CET/CEST", "major_cities": ["Paris", "Madrid", "Rome"], "population": 250000000_i64 },
            { "id": "Europe/Moscow", "name": "Moscow Time", "offset": "+03:00", "dst": false, "abbreviation": "MSK", "major_cities": ["Moscow", "Istanbul", "Nairobi"], "population": 250000000_i64 },
            { "id": "Asia/Dubai", "name": "Gulf Standard Time", "offset": "+04:00", "dst": false, "abbreviation": "GST", "major_cities": ["Dubai", "Abu Dhabi", "Muscat"], "population": 65000000_i64 },
            { "id": "Asia/Shanghai", "name": "China Standard Time", "offset": "+08:00", "dst": false, "abbreviation": "CST", "major_cities": ["Shanghai", "Beijing", "Hong Kong"], "population": 1400000000_i64 },
            { "id": "Asia/Tokyo", "name": "Japan Standard Time", "offset": "+09:00", "dst": false, "abbreviation": "JST", "major_cities": ["Tokyo", "Osaka", "Yokohama"], "population": 127000000_i64 },
            { "id": "Australia/Sydney", "name": "Australian Eastern Time", "offset": "+10:00", "dst": true, "abbreviation": "AEST/AEDT", "major_cities": ["Sydney", "Melbourne", "Brisbane"], "population": 25000000_i64 }
        ],
        "timezone_groups": {
            "us_timezones": ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"],
            "europe_timezones": ["Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow"],
            "asia_timezones": ["Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai"]
        }
    })
}

fn current_world_times() -> Value {
    // (city, IANA timezone) — matches the Go resource's city list.
    const CITIES: &[(&str, &str)] = &[
        ("New York", "America/New_York"),
        ("Los Angeles", "America/Los_Angeles"),
        ("London", "Europe/London"),
        ("Paris", "Europe/Paris"),
        ("Tokyo", "Asia/Tokyo"),
        ("Sydney", "Australia/Sydney"),
        ("Dubai", "Asia/Dubai"),
        ("Singapore", "Asia/Singapore"),
        ("Mumbai", "Asia/Kolkata"),
        ("Hong Kong", "Asia/Hong_Kong"),
    ];
    let now = Utc::now();
    let mut times = serde_json::Map::new();
    for (city, tz) in CITIES {
        let value = match parse_timezone(tz) {
            Ok(zone) => zone.format_local(now, "%Y-%m-%d %H:%M:%S %Z"),
            Err(_) => "Error loading timezone".to_string(),
        };
        times.insert((*city).to_string(), Value::String(value));
    }
    json!({
        "last_updated": now.to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        "times": Value::Object(times)
    })
}

fn time_formats() -> Value {
    json!({
        "input_formats": [
            "2006-01-02 15:04:05",
            "2006-01-02T15:04:05Z",
            "2006-01-02T15:04:05-07:00",
            "Jan 2, 2006 3:04 PM",
            "Monday, January 2, 2006",
            "02/01/2006 15:04"
        ],
        "output_formats": {
            "iso8601": "2006-01-02T15:04:05Z07:00",
            "rfc3339": "2006-01-02T15:04:05Z",
            "rfc822": "Mon, 02 Jan 2006 15:04:05 MST",
            "unix": "1136214245",
            "human_readable": "Monday, January 2, 2006 at 3:04 PM",
            "short": "1/2/06 3:04 PM"
        },
        "examples": [
            { "format": "ISO 8601", "example": "2024-01-15T14:30:00-05:00", "description": "Standard international format with timezone" },
            { "format": "Unix Timestamp", "example": "1705339800", "description": "Seconds since January 1, 1970 UTC" },
            { "format": "RFC 3339", "example": "2024-01-15T14:30:00Z", "description": "Internet standard format" }
        ]
    })
}

fn business_hours() -> Value {
    json!({
        "regions": {
            "north_america": { "standard_hours": "9:00 AM - 5:00 PM", "lunch_break": "12:00 PM - 1:00 PM", "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] },
            "europe": { "standard_hours": "9:00 AM - 6:00 PM", "lunch_break": "1:00 PM - 2:00 PM", "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] },
            "asia_pacific": { "standard_hours": "9:00 AM - 6:00 PM", "lunch_break": "12:00 PM - 1:00 PM", "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] },
            "middle_east": { "standard_hours": "9:00 AM - 6:00 PM", "lunch_break": "1:00 PM - 2:00 PM", "working_days": ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"] }
        },
        "holidays": {
            "global": ["New Year's Day", "Christmas Day"],
            "regional": {
                "us": ["Independence Day", "Thanksgiving", "Memorial Day", "Labor Day"],
                "uk": ["Boxing Day", "Spring Bank Holiday", "Summer Bank Holiday"],
                "japan": ["Golden Week", "Obon", "New Year Holiday"],
                "china": ["Spring Festival", "Mid-Autumn Festival", "National Day"]
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_list_exposes_all_resources() {
        let uris: Vec<String> = list().into_iter().map(|r| r.raw.uri).collect();
        assert_eq!(
            uris,
            [
                "timezone://info",
                "time://current/world",
                "time://formats",
                "time://business-hours",
            ]
        );
    }

    #[test]
    fn test_read_timezone_info_matches_go_shape() {
        let result = read("timezone://info").expect("timezone info resource should exist");
        let contents = &result.contents[0];
        let text = match contents {
            ResourceContents::TextResourceContents { text, uri, .. } => {
                assert_eq!(uri, "timezone://info");
                text
            }
            _ => panic!("expected text resource contents"),
        };
        let data: Value = serde_json::from_str(text).expect("resource body should be JSON");
        assert_eq!(data["timezones"].as_array().unwrap().len(), 11);
        assert!(data["timezone_groups"]["us_timezones"].is_array());
    }

    #[test]
    fn test_read_unknown_resource_is_not_found() {
        let err = read("time://nope").expect_err("unknown resource should error");
        assert_eq!(err.code, rmcp::model::ErrorCode::RESOURCE_NOT_FOUND);
    }

    #[test]
    fn test_world_times_includes_all_cities() {
        let result = read("time://current/world").unwrap();
        let ResourceContents::TextResourceContents { text, .. } = &result.contents[0] else {
            panic!("expected text");
        };
        let data: Value = serde_json::from_str(text).unwrap();
        assert_eq!(data["times"].as_object().unwrap().len(), 10);
        assert!(data["last_updated"].is_string());
    }
}
