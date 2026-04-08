// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use axum::{
    Json,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::{Map, Value, json};

use crate::core_auth_policy;

pub(crate) fn normalize_auth_context(auth_context: Value) -> Result<Value, Response> {
    let Value::Object(mut auth_context) = auth_context else {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    };

    if let Some(teams) = auth_context.get("teams").cloned() {
        match teams {
            Value::Null => {
                if !auth_context
                    .get("is_admin")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                {
                    auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
                }
            }
            Value::Array(raw_teams) => {
                let normalized_payload = Value::Object(
                    [("teams".to_string(), Value::Array(raw_teams))]
                        .into_iter()
                        .collect::<Map<String, Value>>(),
                );
                let normalized_teams = core_auth_policy::normalize_token_teams(&normalized_payload)
                    .unwrap_or_default();
                auth_context.insert(
                    "teams".to_string(),
                    Value::Array(normalized_teams.into_iter().map(Value::String).collect()),
                );
            }
            _ => {
                return Err(json_response_with_code(
                    StatusCode::BAD_GATEWAY,
                    "invalid_auth_context",
                    json!({"detail": "Auth service received invalid auth context"}),
                ));
            }
        }
    } else if !auth_context
        .get("is_admin")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
    }

    let token_use = auth_context
        .get("token_use")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let email = auth_context.get("email").and_then(Value::as_str);
    let is_authenticated = auth_context
        .get("is_authenticated")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if token_use != "session" && is_authenticated && email.is_none_or(str::is_empty) {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    }
    if is_authenticated
        && let Some(token_payload) = auth_context
            .get("policy_inputs")
            .and_then(Value::as_object)
            .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        && let Some(token_email) = token_payload.as_object().and_then(|payload| {
            payload
                .get("sub")
                .and_then(Value::as_str)
                .or_else(|| payload.get("email").and_then(Value::as_str))
        })
        && email != Some(token_email)
    {
        return Err(json_response_with_code(
            StatusCode::BAD_GATEWAY,
            "invalid_auth_context",
            json!({"detail": "Auth service received invalid auth context"}),
        ));
    }
    if token_use != "session" {
        if let Some(policy_payload) = auth_context
            .get("policy_inputs")
            .and_then(Value::as_object)
            .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        {
            let normalized_teams = core_auth_policy::normalize_token_teams(policy_payload);
            auth_context.insert(
                "teams".to_string(),
                match normalized_teams {
                    None => Value::Null,
                    Some(teams) => Value::Array(teams.into_iter().map(Value::String).collect()),
                },
            );
        }
    } else if let Some(policy_inputs) = auth_context.get("policy_inputs").and_then(Value::as_object)
    {
        let session_email = auth_context.get("email").and_then(Value::as_str);
        if session_email.is_none_or(str::is_empty) {
            auth_context.insert("teams".to_string(), Value::Array(Vec::new()));
        } else if policy_inputs
            .get("db_user_is_admin")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            auth_context.insert("teams".to_string(), Value::Null);
        } else if let Some(policy_payload) = policy_inputs.get("token_payload") {
            let db_teams = match policy_inputs.get("db_teams") {
                Some(Value::Null) => {
                    return Err(json_response_with_code(
                        StatusCode::BAD_GATEWAY,
                        "invalid_auth_context",
                        json!({"detail": "Auth service received invalid auth context"}),
                    ));
                }
                Some(Value::Array(db_teams)) => Some(
                    db_teams
                        .iter()
                        .filter_map(Value::as_str)
                        .map(std::string::ToString::to_string)
                        .collect::<Vec<_>>(),
                ),
                _ => {
                    return Err(json_response_with_code(
                        StatusCode::BAD_GATEWAY,
                        "invalid_auth_context",
                        json!({"detail": "Auth service received invalid auth context"}),
                    ));
                }
            };

            let resolved_teams = core_auth_policy::resolve_session_teams(
                policy_payload,
                session_email,
                db_teams.as_deref(),
            );
            auth_context.insert(
                "teams".to_string(),
                match resolved_teams {
                    None => Value::Null,
                    Some(teams) => Value::Array(teams.into_iter().map(Value::String).collect()),
                },
            );
        }
    }

    let token_use = auth_context
        .get("token_use")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let team_id = auth_context
        .get("teams")
        .and_then(primary_team_id)
        .filter(|_| token_use != "session");
    if let Some(team_id) = team_id {
        auth_context.insert("team_id".to_string(), Value::String(team_id));
    } else if auth_context.contains_key("team_id") {
        auth_context.insert("team_id".to_string(), Value::Null);
    }

    let normalized_teams = auth_context.get("teams");
    let primary_team_id = normalized_teams.and_then(primary_team_id);
    let team_name = derive_team_name(
        auth_context.get("policy_inputs").and_then(Value::as_object),
        &token_use,
        primary_team_id.as_deref(),
    );
    if let Some(team_name) = team_name {
        auth_context.insert("team_name".to_string(), Value::String(team_name));
    } else if auth_context.contains_key("team_name") && primary_team_id.is_none() {
        auth_context.insert("team_name".to_string(), Value::Null);
    }

    let token_payload = auth_context
        .get("policy_inputs")
        .and_then(Value::as_object)
        .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        .cloned();

    let scoped_permissions = derive_scoped_permissions(token_payload.as_ref());
    if let Some(scoped_permissions) = scoped_permissions {
        auth_context.insert(
            "scoped_permissions".to_string(),
            Value::Array(scoped_permissions.into_iter().map(Value::String).collect()),
        );
    }

    let scoped_server_id = derive_scoped_server_id(token_payload.as_ref());
    if let Some(scoped_server_id) = scoped_server_id {
        auth_context.insert(
            "scoped_server_id".to_string(),
            Value::String(scoped_server_id),
        );
    }

    let permission_is_admin = derive_permission_is_admin(
        auth_context.get("policy_inputs").and_then(Value::as_object),
        auth_context
            .get("is_admin")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    auth_context.insert(
        "permission_is_admin".to_string(),
        Value::Bool(permission_is_admin),
    );

    if has_token_payload(auth_context.get("policy_inputs").and_then(Value::as_object)) {
        auth_context.insert("auth_method".to_string(), Value::String("jwt".to_string()));
    }

    Ok(Value::Object(auth_context))
}

fn primary_team_id(teams: &Value) -> Option<String> {
    match teams {
        Value::Array(team_values) if team_values.len() == 1 => team_values
            .first()
            .and_then(Value::as_str)
            .map(str::to_string),
        _ => None,
    }
}

fn derive_team_name(
    policy_inputs: Option<&Map<String, Value>>,
    token_use: &str,
    primary_team_id: Option<&str>,
) -> Option<String> {
    let primary_team_id = primary_team_id?;
    let policy_inputs = policy_inputs?;

    if let Some(team_name) = policy_inputs
        .get("team_names")
        .and_then(Value::as_object)
        .and_then(|team_names| team_names.get(primary_team_id))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|team_name| !team_name.is_empty())
    {
        return Some(team_name.to_string());
    }

    if token_use == "session" {
        return None;
    }

    let token_payload = policy_inputs.get("token_payload")?.as_object()?;
    let raw_teams = token_payload.get("teams")?.as_array()?;
    for raw_team in raw_teams {
        match raw_team {
            Value::Object(raw_team)
                if raw_team.get("id").and_then(Value::as_str) == Some(primary_team_id) =>
            {
                if let Some(team_name) = raw_team
                    .get("name")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|team_name| !team_name.is_empty())
                {
                    return Some(team_name.to_string());
                }
            }
            Value::String(raw_team_id) if raw_team_id == primary_team_id => return None,
            _ => {}
        }
    }

    None
}

fn derive_scoped_permissions(token_payload: Option<&Value>) -> Option<Vec<String>> {
    let token_payload = token_payload?.as_object()?;
    let scopes = token_payload.get("scopes")?.as_object()?;
    let permissions = scopes.get("permissions")?.as_array()?;
    Some(
        permissions
            .iter()
            .filter_map(Value::as_str)
            .map(str::trim)
            .filter(|permission| !permission.is_empty())
            .map(str::to_string)
            .collect(),
    )
}

fn derive_scoped_server_id(token_payload: Option<&Value>) -> Option<String> {
    token_payload
        .and_then(Value::as_object)
        .and_then(|token_payload| token_payload.get("scopes"))
        .and_then(Value::as_object)
        .and_then(|scopes| scopes.get("server_id"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|server_id| !server_id.is_empty())
        .map(str::to_string)
}

fn derive_permission_is_admin(policy_inputs: Option<&Map<String, Value>>, is_admin: bool) -> bool {
    let db_user_is_admin = policy_inputs
        .and_then(|policy_inputs| policy_inputs.get("db_user_is_admin"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    db_user_is_admin || is_admin
}

fn has_token_payload(policy_inputs: Option<&Map<String, Value>>) -> bool {
    policy_inputs
        .and_then(|policy_inputs| policy_inputs.get("token_payload"))
        .is_some()
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    (status, Json(payload)).into_response()
}

fn json_response_with_code(status: StatusCode, code: &str, payload: Value) -> Response {
    let payload = match payload {
        Value::Object(mut payload) => {
            payload.insert("code".to_string(), Value::String(code.to_string()));
            Value::Object(payload)
        }
        other => other,
    };
    json_response(status, payload)
}
