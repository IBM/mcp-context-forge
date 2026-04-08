// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use axum::{
    Json, Router,
    extract::State,
    response::IntoResponse,
    routing::{get, post},
};
use tokio_stream::wrappers::UnixListenerStream;
use tonic::{Request, Response as GrpcResponse, Status, transport::Server};

use crate::{
    DenyResponse,
    error::SidecarError,
    flow::proxy_authenticate,
    rpc,
    state::AppState,
    types::{AuthenticateRequest, HealthResponse},
};

#[derive(Clone)]
struct AuthRpcService {
    state: AppState,
}

#[tonic::async_trait]
impl rpc::auth_service_server::AuthService for AuthRpcService {
    async fn authenticate(
        &self,
        request: Request<rpc::AuthenticateRequest>,
    ) -> Result<GrpcResponse<rpc::AuthenticateReply>, Status> {
        match proxy_authenticate(&self.state, &request.into_inner().into()).await {
            Ok(response) => Ok(GrpcResponse::new(rpc::AuthenticateReply {
                outcome: Some(rpc::authenticate_reply::Outcome::AuthContext(
                    response.auth_context.into(),
                )),
            })),
            Err(response) => {
                let deny = deny_from_response(response).await;
                Ok(GrpcResponse::new(rpc::AuthenticateReply {
                    outcome: Some(rpc::authenticate_reply::Outcome::Deny(deny.into())),
                }))
            }
        }
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(health))
        .route("/_internal/core/auth/authenticate", post(authenticate))
        .with_state(state)
}

pub async fn run(config: crate::config::AuthConfig) -> Result<(), SidecarError> {
    let state = AppState::new(&config)?;
    verify_backend_readiness(&state).await?;

    match config.listen_uds.clone() {
        Some(path) => {
            let grpc_state = state.clone();
            let grpc_path = path.clone();
            let grpc = async move {
                if grpc_path.exists() {
                    std::fs::remove_file(&grpc_path)?;
                }
                let listener = tokio::net::UnixListener::bind(&grpc_path)?;
                let incoming = UnixListenerStream::new(listener);
                Server::builder()
                    .add_service(rpc::auth_service_server::AuthServiceServer::new(
                        AuthRpcService { state: grpc_state },
                    ))
                    .serve_with_incoming(incoming)
                    .await
                    .map_err(SidecarError::from)
            };

            let listener =
                tokio::net::TcpListener::bind(config.listen_addr().map_err(SidecarError::Config)?)
                    .await?;
            let http = async move {
                axum::serve(listener, build_router(state))
                    .await
                    .map_err(SidecarError::from)
            };

            tokio::try_join!(grpc, http)?;
        }
        None => {
            let listener =
                tokio::net::TcpListener::bind(config.listen_addr().map_err(SidecarError::Config)?)
                    .await?;
            axum::serve(listener, build_router(state)).await?;
        }
    }
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

async fn deny_from_response(response: axum::response::Response) -> DenyResponse {
    let status = response.status().as_u16();
    let www_authenticate = response
        .headers()
        .get(axum::http::header::WWW_AUTHENTICATE)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap_or_default();
    let payload = serde_json::from_slice::<serde_json::Value>(&body).ok();
    DenyResponse {
        status,
        detail: payload
            .as_ref()
            .and_then(|value| value.get("detail"))
            .and_then(serde_json::Value::as_str)
            .unwrap_or("Auth denied")
            .to_string(),
        code: payload
            .as_ref()
            .and_then(|value| value.get("code"))
            .and_then(serde_json::Value::as_str)
            .map(str::to_string),
        www_authenticate,
    }
}
