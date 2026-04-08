// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Core-owned auth policy helpers shared by the auth service.

use serde_json::{Map, Value};

#[must_use]
pub fn normalize_token_teams(payload: &Value) -> Option<Vec<String>> {
    let Some(payload) = payload.as_object() else {
        return Some(Vec::new());
    };

    if !payload.contains_key("teams") {
        return Some(Vec::new());
    }

    let teams = payload.get("teams").unwrap_or(&Value::Null);
    if teams.is_null() {
        let mut is_admin = payload
            .get("is_admin")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if !is_admin {
            is_admin = payload
                .get("user")
                .and_then(Value::as_object)
                .and_then(|user| user.get("is_admin"))
                .and_then(Value::as_bool)
                .unwrap_or(false);
        }
        return if is_admin { None } else { Some(Vec::new()) };
    }

    let Some(teams) = teams.as_array() else {
        return Some(Vec::new());
    };

    Some(
        teams
            .iter()
            .filter_map(|team| match team {
                Value::String(team_id) => Some(team_id.clone()),
                Value::Object(team_obj) => team_obj
                    .get("id")
                    .and_then(Value::as_str)
                    .map(std::string::ToString::to_string),
                _ => None,
            })
            .collect(),
    )
}

#[must_use]
pub fn resolve_session_teams(payload: &Value, email: Option<&str>, db_teams: Option<&[String]>) -> Option<Vec<String>> {
    if email.is_none_or(str::is_empty) {
        return Some(Vec::new());
    }

    let Some(db_teams) = db_teams else {
        return None;
    };

    let jwt_teams = payload
        .as_object()
        .and_then(|payload| payload.get("teams"))
        .and_then(Value::as_array);

    if let Some(jwt_teams) = jwt_teams.filter(|teams| !teams.is_empty()) {
        let normalized_payload = Value::Object(
            [("teams".to_string(), Value::Array(jwt_teams.clone()))]
                .into_iter()
                .collect::<Map<String, Value>>(),
        );
        let normalized = normalize_token_teams(&normalized_payload).unwrap_or_default();

        return Some(
            db_teams
                .iter()
                .filter(|team| normalized.iter().any(|candidate| candidate == *team))
                .cloned()
                .collect(),
        );
    }

    Some(db_teams.to_vec())
}

#[cfg(test)]
mod tests {
    use super::{normalize_token_teams, resolve_session_teams};
    use serde::Deserialize;
    use serde_json::Value;

    #[derive(Debug, Deserialize)]
    struct NormalizeCase {
        name: String,
        payload: Value,
        expected: Option<Vec<String>>,
    }

    #[derive(Debug, Deserialize)]
    struct ResolveSessionCase {
        name: String,
        payload: Value,
        email: Option<String>,
        db_teams: Option<Vec<String>>,
        expected: Option<Vec<String>>,
    }

    #[derive(Debug, Deserialize)]
    struct Oracle {
        normalize_token_teams: Vec<NormalizeCase>,
        resolve_session_teams: Vec<ResolveSessionCase>,
    }

    fn oracle() -> Oracle {
        serde_json::from_str(include_str!("../../../tests/fixtures/core_auth_policy_oracle.json"))
            .expect("parse core auth policy oracle")
    }

    #[test]
    fn normalize_token_teams_matches_oracle() {
        let oracle = oracle();
        for case in oracle.normalize_token_teams {
            assert_eq!(
                normalize_token_teams(&case.payload),
                case.expected,
                "normalize_token_teams oracle case failed: {}",
                case.name
            );
        }
    }

    #[test]
    fn resolve_session_teams_matches_oracle() {
        let oracle = oracle();
        for case in oracle.resolve_session_teams {
            assert_eq!(
                resolve_session_teams(&case.payload, case.email.as_deref(), case.db_teams.as_deref()),
                case.expected,
                "resolve_session_teams oracle case failed: {}",
                case.name
            );
        }
    }
}
