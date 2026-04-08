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
    pub headers: std::collections::HashMap<String, String>,
    #[serde(default)]
    pub client_ip: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticateResponse {
    pub auth_context: Value,
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
