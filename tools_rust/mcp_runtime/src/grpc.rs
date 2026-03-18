// Location: tools_rust/mcp_runtime/src/grpc.rs
// SPDX-License-Identifier: Apache-2.0
//
// gRPC-over-UDS server for the Rust MCP runtime sidecar (ADR-044).
//
// Replaces the HTTP/JSON proxy boundary with a typed protobuf contract over a
// Unix Domain Socket.  The gRPC service handlers call the shared `_inner`
// handler functions directly — no http::Request encoding, no Tower/Axum
// dispatch overhead.
//
// Feature-gated: only compiled when `--features grpc-uds` is set.

use std::path::PathBuf;
use std::pin::Pin;

use bytes::Bytes;
use futures_util::StreamExt;
use http::{HeaderName, HeaderValue, Uri};
use http_body_util::BodyExt;
use axum::http::HeaderMap;
use tokio::net::UnixListener;
use tokio_stream::Stream;
use tonic::codec::CompressionEncoding;
use tonic::{Request as TonicRequest, Response as TonicResponse, Status};
use tracing::{debug, error, info};

use crate::AppState;

// ---------------------------------------------------------------------------
// Include the tonic-generated types for the mcp_runtime.proto service
// ---------------------------------------------------------------------------

pub mod proto {
    tonic::include_proto!("contextforge.mcp.runtime.v1");
}

use proto::mcp_runtime_server::{McpRuntime, McpRuntimeServer};
use proto::{HealthRequest, HealthResponse, McpChunk, McpRequest, McpResponse};

// ---------------------------------------------------------------------------
// Service implementation
// ---------------------------------------------------------------------------

/// gRPC service that calls into the shared MCP handler functions directly.
///
/// Each RPC handler converts the incoming protobuf [`McpRequest`] into the
/// plain Rust types that the `_inner` handler functions accept (`HeaderMap`,
/// `Uri`, `Bytes`) and calls them without any HTTP encoding round-trip.
#[derive(Clone)]
pub struct McpRuntimeService {
    state: AppState,
    mode: String,
    version: String,
}

impl McpRuntimeService {
    pub fn new(state: AppState, mode: impl Into<String>, version: impl Into<String>) -> Self {
        Self {
            state,
            mode: mode.into(),
            version: version.into(),
        }
    }
}

// ---------------------------------------------------------------------------
// Helper: build HeaderMap from proto McpRequest fields
// ---------------------------------------------------------------------------

fn build_headers(req: &McpRequest) -> Result<HeaderMap, Status> {
    let mut headers = HeaderMap::new();

    for (name, value) in &req.headers {
        let header_name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| Status::invalid_argument(format!("invalid header name: {name}")))?;
        let header_value = HeaderValue::from_str(value)
            .map_err(|_| Status::invalid_argument(format!("invalid header value for {name}")))?;
        headers.insert(header_name, header_value);
    }

    // Inject trusted internal headers that the handler functions expect
    if !req.server_id.is_empty() {
        headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_str(&req.server_id)
                .map_err(|_| Status::invalid_argument("invalid server_id"))?,
        );
    }

    if let Some(auth) = &req.auth_context {
        if !auth.encoded.is_empty() {
            headers.insert(
                HeaderName::from_static("x-contextforge-auth-context"),
                HeaderValue::from_str(&auth.encoded)
                    .map_err(|_| Status::invalid_argument("invalid auth_context encoding"))?,
            );
        }
    }

    if req.affinity_forwarded {
        headers.insert(
            HeaderName::from_static("x-contextforge-affinity-forwarded"),
            HeaderValue::from_static("rust"),
        );
    }

    if !req.session_id.is_empty() {
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_str(&req.session_id)
                .map_err(|_| Status::invalid_argument("invalid session_id"))?,
        );
    }

    Ok(headers)
}

// ---------------------------------------------------------------------------
// Helper: build Uri from path + query
// ---------------------------------------------------------------------------

fn build_uri(path: &str, query: &str) -> Result<Uri, Status> {
    let uri_str = if query.is_empty() {
        path.to_owned()
    } else {
        format!("{path}?{query}")
    };
    uri_str
        .parse::<Uri>()
        .map_err(|_| Status::invalid_argument(format!("invalid URI: {uri_str}")))
}

// ---------------------------------------------------------------------------
// Helper: non-empty string → Option<String>
// ---------------------------------------------------------------------------

fn non_empty(s: String) -> Option<String> {
    if s.is_empty() { None } else { Some(s) }
}

// ---------------------------------------------------------------------------
// Helper: axum Response → proto McpResponse (unary)
// ---------------------------------------------------------------------------

async fn response_to_proto(response: axum::response::Response) -> Result<McpResponse, Status> {
    let status = response.status().as_u16() as i32;

    let mut headers = std::collections::HashMap::new();
    for (name, value) in response.headers() {
        if let Ok(v) = value.to_str() {
            headers.insert(name.as_str().to_owned(), v.to_owned());
        }
    }

    let body_bytes = response
        .into_body()
        .collect()
        .await
        .map_err(|e| Status::internal(format!("failed to read response body: {e}")))?
        .to_bytes();

    Ok(McpResponse {
        status,
        headers,
        body: body_bytes.to_vec(),
    })
}

// ---------------------------------------------------------------------------
// Helper: axum Response → stream of McpChunk (server-streaming)
// ---------------------------------------------------------------------------

fn response_to_chunk_stream(
    response: axum::response::Response,
) -> Pin<Box<dyn Stream<Item = Result<McpChunk, Status>> + Send>> {
    let status = response.status().as_u16();
    let body = response.into_body();

    Box::pin(async_stream::try_stream! {
        if status >= 400 {
            yield McpChunk {
                data: Vec::new(),
                done: true,
                error_status: status as i32,
            };
            return;
        }

        let mut body_stream = body.into_data_stream();
        while let Some(chunk) = body_stream.next().await {
            match chunk {
                Ok(bytes) if !bytes.is_empty() => {
                    yield McpChunk {
                        data: bytes.to_vec(),
                        done: false,
                        error_status: 0,
                    };
                }
                Ok(_) => {}
                Err(e) => {
                    error!("gRPC stream: body read error: {e}");
                    Err(Status::internal(format!("body read error: {e}")))?;
                }
            }
        }

        // Terminal chunk signals end-of-stream to the Python client
        yield McpChunk {
            data: Vec::new(),
            done: true,
            error_status: 0,
        };
    })
}

// ---------------------------------------------------------------------------
// McpRuntime trait implementation
// ---------------------------------------------------------------------------

#[tonic::async_trait]
impl McpRuntime for McpRuntimeService {
    type InvokeStreamStream = Pin<Box<dyn Stream<Item = Result<McpChunk, Status>> + Send>>;

    /// Unary: POST /mcp — initialize, tools/call, tools/list, resources/*, prompts/*
    async fn invoke(
        &self,
        request: TonicRequest<McpRequest>,
    ) -> Result<TonicResponse<McpResponse>, Status> {
        let r = request.into_inner();
        debug!("gRPC Invoke: path={}", r.path);

        let headers = build_headers(&r)?;
        let uri = build_uri(&r.path, &r.query)?;
        let body = Bytes::from(r.body);
        let server_id = non_empty(r.server_id);

        let response = crate::rpc_inner(self.state.clone(), None, headers, uri, body, server_id).await;

        let proto_resp = response_to_proto(response).await?;
        Ok(TonicResponse::new(proto_resp))
    }

    /// Server-streaming: GET /mcp — SSE / live-stream / resume
    async fn invoke_stream(
        &self,
        request: TonicRequest<McpRequest>,
    ) -> Result<TonicResponse<Self::InvokeStreamStream>, Status> {
        let r = request.into_inner();
        debug!("gRPC InvokeStream: path={}", r.path);

        let headers = build_headers(&r)?;
        let uri = build_uri(&r.path, &r.query)?;
        let server_id = non_empty(r.server_id);

        let response = crate::transport_get_inner(self.state.clone(), None, headers, uri, server_id).await;

        Ok(TonicResponse::new(response_to_chunk_stream(response)))
    }

    /// Unary: DELETE /mcp — session close
    async fn close_session(
        &self,
        request: TonicRequest<McpRequest>,
    ) -> Result<TonicResponse<McpResponse>, Status> {
        let r = request.into_inner();
        debug!("gRPC CloseSession: session_id={}", r.session_id);

        let headers = build_headers(&r)?;
        let uri = build_uri(&r.path, &r.query)?;
        let server_id = non_empty(r.server_id);

        let response = crate::transport_delete_inner(self.state.clone(), None, headers, uri, server_id).await;

        let proto_resp = response_to_proto(response).await?;
        Ok(TonicResponse::new(proto_resp))
    }

    /// Unary: health probe used by Python entrypoint readiness check
    async fn health_check(
        &self,
        _request: TonicRequest<HealthRequest>,
    ) -> Result<TonicResponse<HealthResponse>, Status> {
        Ok(TonicResponse::new(HealthResponse {
            status: "ok".to_owned(),
            mode: self.mode.clone(),
            version: self.version.clone(),
        }))
    }
}

// ---------------------------------------------------------------------------
// gRPC server startup
// ---------------------------------------------------------------------------

/// Start the gRPC-over-UDS server alongside the existing Axum HTTP server.
///
/// Binds a `tonic` gRPC server to `uds_path`.  Each incoming RPC calls the
/// shared `_inner` handler functions directly — no HTTP encoding round-trip.
pub async fn serve_grpc_uds(
    state: AppState,
    uds_path: PathBuf,
    mode: String,
    version: String,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if uds_path.exists() {
        std::fs::remove_file(&uds_path)?;
    }

    info!("starting gRPC-over-UDS server on unix://{}", uds_path.display());

    let service = McpRuntimeService::new(state, mode, version);
    let server = McpRuntimeServer::new(service)
        .accept_compressed(CompressionEncoding::Gzip)
        .send_compressed(CompressionEncoding::Gzip);

    let uds = UnixListener::bind(&uds_path)?;
    let incoming = tokio_stream::wrappers::UnixListenerStream::new(uds);

    tonic::transport::Server::builder()
        .add_service(server)
        .serve_with_incoming(incoming)
        .await?;

    Ok(())
}
