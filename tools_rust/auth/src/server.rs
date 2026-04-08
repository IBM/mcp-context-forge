// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use axum::{
    Json, Router,
    extract::State,
    response::IntoResponse,
    routing::{get, post},
};

use crate::{
    error::SidecarError,
    flow::proxy_authenticate,
    state::AppState,
    types::{AuthenticateRequest, HealthResponse},
};

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(health))
        .route("/_internal/core/auth/authenticate", post(authenticate))
        .with_state(state)
}

pub async fn run(config: crate::config::AuthConfig) -> Result<(), SidecarError> {
    let state = AppState::new(&config)?;
    verify_backend_readiness(&state).await?;
    let listener =
        tokio::net::TcpListener::bind(config.listen_addr().map_err(SidecarError::Config)?).await?;
    axum::serve(listener, build_router(state)).await?;
    Ok(())
}

pub(crate) async fn verify_backend_readiness(state: &AppState) -> Result<(), SidecarError> {
    let Some(health_url) = state.backend_health_url() else {
        return Ok(());
    };

    let response =
        state.client.get(health_url).send().await.map_err(|err| {
            SidecarError::BackendReadiness(format!("GET {health_url} failed: {err}"))
        })?;

    if !response.status().is_success() {
        return Err(SidecarError::BackendReadiness(format!(
            "GET {health_url} returned {}",
            response.status()
        )));
    }

    Ok(())
}

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        runtime: "contextforge-auth",
        backend_authenticate_url: state.backend_authenticate_url().to_string(),
        backend_health_url: state.backend_health_url().map(str::to_string),
        experimental_direct_auth: state.experimental_direct_auth,
        shadow_compare_direct_auth: state.shadow_compare_direct_auth,
        auth_stats: state.auth_stats.snapshot(),
    })
}

async fn authenticate(
    State(state): State<AppState>,
    Json(request): Json<AuthenticateRequest>,
) -> axum::response::Response {
    match proxy_authenticate(&state, &request).await {
        Ok(response) => Json(response).into_response(),
        Err(response) => response,
    }
}
