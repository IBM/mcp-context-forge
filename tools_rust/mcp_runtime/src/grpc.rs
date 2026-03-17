// Location: tools_rust/mcp_runtime/src/grpc.rs
// SPDX-License-Identifier: Apache-2.0
//
// gRPC-over-UDS server for the Rust MCP runtime sidecar (ADR-044).
//
// Replaces the HTTP/JSON proxy boundary (rust_mcp_runtime_proxy.py) with a
// typed protobuf contract.  The gRPC service handlers convert incoming proto
// messages into `http::Request` objects and call the existing Axum router
// directly as a Tower service — no additional network hop inside the sidecar.
//
// Feature-gated: only compiled when `--features grpc-uds` is set.

use std::path::PathBuf;
use std::pin::Pin;

use axum::Router;
use axum::body::Body;
use bytes::Bytes;
use futures_util::StreamExt;
use http::{HeaderName, HeaderValue, Method, Request, Uri, Version};
use http_body_util::BodyExt;
use tokio::net::UnixListener;
use tokio_stream::Stream;
use tonic::codec::CompressionEncoding;
use tonic::{Request as TonicRequest, Response as TonicResponse, Status};
use tower::ServiceExt;
use tracing::{debug, error, info};

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

/// gRPC service that wraps the existing Axum MCP router.
///
/// Each RPC handler converts the incoming protobuf [`McpRequest`] into an
/// [`http::Request`], calls the Axum router as a Tower service, and converts
/// the [`http::Response`] back into the appropriate proto response type.
#[derive(Clone)]
pub struct McpRuntimeService {
    /// The internal Axum router (same instance as the HTTP/UDS server).
    router: Router,
    /// Sidecar mode string forwarded in health responses.
    mode: String,
    /// Sidecar version string forwarded in health responses.
    version: String,
}

impl McpRuntimeService {
    pub fn new(router: Router, mode: impl Into<String>, version: impl Into<String>) -> Self {
        Self {
            router,
            mode: mode.into(),
            version: version.into(),
        }
    }
}

// ---------------------------------------------------------------------------
// Helper: proto McpRequest → http::Request<Body>
// ---------------------------------------------------------------------------

fn proto_to_http_request(req: &McpRequest) -> Result<Request<Body>, Status> {
    let method = Method::from_bytes(req.method.as_bytes())
        .map_err(|_| Status::invalid_argument(format!("invalid HTTP method: {}", req.method)))?;

    let uri_str = if req.query.is_empty() {
        req.path.clone()
    } else {
        format!("{}?{}", req.path, req.query)
    };
    let uri = uri_str
        .parse::<Uri>()
        .map_err(|_| Status::invalid_argument(format!("invalid URI: {uri_str}")))?;

    let mut builder = Request::builder().method(method).uri(uri).version(Version::HTTP_11);

    // Forward safe headers from the proto map
    for (name, value) in &req.headers {
        let header_name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| Status::invalid_argument(format!("invalid header name: {name}")))?;
        let header_value = HeaderValue::from_str(value)
            .map_err(|_| Status::invalid_argument(format!("invalid header value for {name}")))?;
        builder = builder.header(header_name, header_value);
    }

    // Inject server-id as the trusted internal header the Axum handlers expect
    if !req.server_id.is_empty() {
        builder = builder.header("x-contextforge-server-id", &req.server_id);
    }

    // Inject the encoded auth context forwarded from Python
    if let Some(auth) = &req.auth_context {
        if !auth.encoded.is_empty() {
            builder = builder.header("x-contextforge-auth-context", &auth.encoded);
        }
    }

    // Inject the affinity-forwarded marker when set
    if req.affinity_forwarded {
        builder = builder.header("x-contextforge-affinity-forwarded", "rust");
    }

    // Inject MCP session ID when present
    if !req.session_id.is_empty() {
        builder = builder.header("mcp-session-id", &req.session_id);
    }

    let body = if req.body.is_empty() {
        Body::empty()
    } else {
        Body::from(Bytes::copy_from_slice(&req.body))
    };

    builder
        .body(body)
        .map_err(|e| Status::internal(format!("failed to build HTTP request: {e}")))
}

// ---------------------------------------------------------------------------
// Helper: http::Response<Body> → proto McpResponse (unary)
// ---------------------------------------------------------------------------

async fn http_response_to_proto(response: http::Response<Body>) -> Result<McpResponse, Status> {
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
// Helper: http::Response<Body> → stream of McpChunk (server-streaming)
// ---------------------------------------------------------------------------

fn http_response_to_chunk_stream(
    response: http::Response<Body>,
) -> Pin<Box<dyn Stream<Item = Result<McpChunk, Status>> + Send>> {
    let status = response.status().as_u16() as u16;
    let body = response.into_body();

    let stream: Pin<Box<dyn Stream<Item = Result<McpChunk, Status>> + Send>> = Box::pin(async_stream::try_stream! {
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
    });

    stream
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
        let mcp_req = request.into_inner();
        debug!("gRPC Invoke: method={} path={}", mcp_req.method, mcp_req.path);

        let http_req = proto_to_http_request(&mcp_req)?;

        let response = self
            .router
            .clone()
            .oneshot(http_req)
            .await
            .map_err(|e| Status::internal(format!("router error: {e}")))?;

        let proto_resp = http_response_to_proto(response).await?;
        Ok(TonicResponse::new(proto_resp))
    }

    /// Server-streaming: GET /mcp — SSE / live-stream / resume
    async fn invoke_stream(
        &self,
        request: TonicRequest<McpRequest>,
    ) -> Result<TonicResponse<Self::InvokeStreamStream>, Status> {
        let mcp_req = request.into_inner();
        debug!("gRPC InvokeStream: method={} path={}", mcp_req.method, mcp_req.path);

        let http_req = proto_to_http_request(&mcp_req)?;

        let response = self
            .router
            .clone()
            .oneshot(http_req)
            .await
            .map_err(|e| Status::internal(format!("router error: {e}")))?;

        Ok(TonicResponse::new(http_response_to_chunk_stream(response)))
    }

    /// Unary: DELETE /mcp — session close
    async fn close_session(
        &self,
        request: TonicRequest<McpRequest>,
    ) -> Result<TonicResponse<McpResponse>, Status> {
        let mcp_req = request.into_inner();
        debug!("gRPC CloseSession: session_id={}", mcp_req.session_id);

        let http_req = proto_to_http_request(&mcp_req)?;

        let response = self
            .router
            .clone()
            .oneshot(http_req)
            .await
            .map_err(|e| Status::internal(format!("router error: {e}")))?;

        let proto_resp = http_response_to_proto(response).await?;
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
/// Binds a `tonic` gRPC server to `uds_path`, wrapping the shared `router`
/// so that every incoming RPC is dispatched directly into the Axum handler
/// tree — no additional network hop.
pub async fn serve_grpc_uds(
    router: Router,
    uds_path: PathBuf,
    mode: String,
    version: String,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if uds_path.exists() {
        std::fs::remove_file(&uds_path)?;
    }

    info!("starting gRPC-over-UDS server on unix://{}", uds_path.display());

    let service = McpRuntimeService::new(router, mode, version);
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
