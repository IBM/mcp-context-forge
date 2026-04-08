// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use crate::stats::AuthStatsSnapshot;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateRequest {
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub query_string: String,
    #[serde(default)]
    pub authorization: Option<String>,
    #[serde(default)]
    pub cookie: Option<String>,
    #[serde(default)]
    pub client_ip: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AuthContext {
    #[serde(default)]
    pub email: Option<String>,
    #[serde(default)]
    pub teams: Option<Vec<String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub team_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub team_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub auth_method: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub permission_is_admin: Option<bool>,
    #[serde(default)]
    pub is_admin: bool,
    #[serde(default)]
    pub is_authenticated: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub token_use: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub jti: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub scoped_permissions: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scoped_server_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub policy_inputs: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateResponse {
    pub auth_context: AuthContext,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DenyResponse {
    pub status: u16,
    pub detail: String,
    #[serde(default)]
    pub code: Option<String>,
    #[serde(default)]
    pub www_authenticate: Option<String>,
}

impl From<AuthenticateRequest> for crate::rpc::AuthenticateRequest {
    fn from(value: AuthenticateRequest) -> Self {
        Self {
            method: value.method,
            path: value.path,
            query_string: value.query_string,
            authorization: value.authorization,
            cookie: value.cookie,
            client_ip: value.client_ip,
        }
    }
}

impl From<crate::rpc::AuthenticateRequest> for AuthenticateRequest {
    fn from(value: crate::rpc::AuthenticateRequest) -> Self {
        Self {
            method: value.method,
            path: value.path,
            query_string: value.query_string,
            authorization: value.authorization,
            cookie: value.cookie,
            client_ip: value.client_ip,
        }
    }
}

impl From<AuthContext> for crate::rpc::AuthContext {
    fn from(value: AuthContext) -> Self {
        Self {
            email: value.email,
            teams_admin_bypass: value.teams.is_none(),
            teams: value.teams.unwrap_or_default(),
            team_name: value.team_name,
            team_id: value.team_id,
            auth_method: value.auth_method,
            permission_is_admin: value.permission_is_admin,
            is_admin: value.is_admin,
            is_authenticated: value.is_authenticated,
            token_use: value.token_use,
            jti: value.jti,
            scoped_permissions: value.scoped_permissions,
            scoped_server_id: value.scoped_server_id,
            policy_inputs_json: value
                .policy_inputs
                .and_then(|value| serde_json::to_string(&value).ok()),
        }
    }
}

impl From<crate::rpc::AuthContext> for AuthContext {
    fn from(value: crate::rpc::AuthContext) -> Self {
        Self {
            email: value.email,
            teams: if value.teams_admin_bypass {
                None
            } else {
                Some(value.teams)
            },
            team_name: value.team_name,
            team_id: value.team_id,
            auth_method: value.auth_method,
            permission_is_admin: value.permission_is_admin,
            is_admin: value.is_admin,
            is_authenticated: value.is_authenticated,
            token_use: value.token_use,
            jti: value.jti,
            scoped_permissions: value.scoped_permissions,
            scoped_server_id: value.scoped_server_id,
            policy_inputs: value
                .policy_inputs_json
                .and_then(|value| serde_json::from_str(&value).ok()),
        }
    }
}

impl From<DenyResponse> for crate::rpc::DenyResponse {
    fn from(value: DenyResponse) -> Self {
        Self {
            status: u32::from(value.status),
            detail: value.detail,
            code: value.code,
            www_authenticate: value.www_authenticate,
        }
    }
}

impl From<crate::rpc::DenyResponse> for DenyResponse {
    fn from(value: crate::rpc::DenyResponse) -> Self {
        Self {
            status: value.status.min(u32::from(u16::MAX)) as u16,
            detail: value.detail,
            code: value.code,
            www_authenticate: value.www_authenticate,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub runtime: &'static str,
    pub backend_authenticate_url: String,
    pub backend_health_url: Option<String>,
    pub experimental_direct_auth: bool,
    pub shadow_compare_direct_auth: bool,
    pub auth_stats: AuthStatsSnapshot,
}
