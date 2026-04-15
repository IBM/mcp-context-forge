// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Native OTEL/Langfuse tracing helpers for the Rust MCP runtime.
//!
//! The Rust runtime reuses the same OTEL and Langfuse environment surface as
//! the Python gateway so operators do not need a second observability config
//! model. This module intentionally mirrors the Python span policy for:
//!
//! - Langfuse attribute emission and identity gating
//! - trace naming and tag derivation
//! - bounded input/output payload capture
//! - secret/URL/bearer/basic redaction for exported span metadata

use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
    io,
    sync::OnceLock,
};

use axum::http::HeaderMap;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use opentelemetry::{
    Array, KeyValue, StringValue, global,
    propagation::Injector,
    trace::{Status, TraceContextExt, TracerProvider as _},
};
use opentelemetry_otlp::{
    Protocol, SpanExporter, WithExportConfig, WithHttpConfig, WithTonicConfig,
};
use opentelemetry_sdk::{
    Resource,
    propagation::TraceContextPropagator,
    runtime,
    trace::{
        BatchConfigBuilder, SdkTracerProvider,
        span_processor_with_async_runtime::BatchSpanProcessor as AsyncBatchSpanProcessor,
    },
};
use regex::Regex;
use serde_json::{Map, Value, json};
use tonic::metadata::{MetadataMap, MetadataValue};
use tracing::{Span, span};
use tracing_opentelemetry::{OpenTelemetrySpanExt, layer as otel_layer};
use tracing_subscriber::{
    EnvFilter, Layer, Registry, filter, layer::SubscriberExt, util::SubscriberInitExt,
};

use crate::InternalAuthContext;

const DEFAULT_REDACT_FIELDS: &str = "password,secret,token,api_key,authorization,credential,auth_value,access_token,refresh_token,auth_token,client_secret,cookie,set-cookie,private_key";
const DEFAULT_MAX_PAYLOAD_SIZE: usize = 32_768;
const MAX_EXCEPTION_MESSAGE_LENGTH: usize = 1_024;
const LANGFUSE_OTEL_PATH_FRAGMENT: &str = "/api/public/otel";
const ELLIPSIS_MARKER: &str = "...";
const TEAM_SCOPE_SEPARATOR: &str = ",";
const URL_REDACTED: &str = "REDACTED";
const OTEL_SPAN_TARGET: &str = "contextforge.mcp.otel";

static OBSERVABILITY_CONFIG: OnceLock<ObservabilityConfig> = OnceLock::new();
static TRACER_PROVIDER: OnceLock<SdkTracerProvider> = OnceLock::new();
static URL_REGEX: OnceLock<Regex> = OnceLock::new();
static BEARER_REGEX: OnceLock<Regex> = OnceLock::new();
static REPEATED_REDACTION_REGEX: OnceLock<Regex> = OnceLock::new();
static STATIC_SENSITIVE_PARAMS: OnceLock<HashSet<String>> = OnceLock::new();

#[derive(Debug, Clone)]
pub struct ObservabilityHandle {
    provider: Option<SdkTracerProvider>,
}

impl ObservabilityHandle {
    #[must_use]
    pub fn disabled() -> Self {
        Self { provider: None }
    }

    pub fn shutdown(self) {
        if let Some(provider) = self.provider {
            let _ = provider.shutdown();
        }
    }
}

#[derive(Debug, Clone)]
struct ObservabilityConfig {
    enabled: bool,
    deployment_env: String,
    service_name: String,
    resource_attributes: Vec<(String, String)>,
    otlp_endpoint: Option<String>,
    otlp_protocol: String,
    otlp_headers: HashMap<String, String>,
    emit_langfuse_attributes: bool,
    capture_identity_attributes: bool,
    redact_fields: HashSet<String>,
    raw_redact_fields: Vec<String>,
    text_redaction_patterns: Vec<TextRedactionPattern>,
    max_trace_payload_size: usize,
    capture_input_spans: HashSet<String>,
    capture_output_spans: HashSet<String>,
}

#[derive(Debug, Clone)]
struct TextRedactionPattern {
    quoted: Regex,
    bare: Regex,
}

#[derive(Debug, Clone, Default)]
pub struct TraceRequestContext {
    pub correlation_id: Option<String>,
    pub request_id: Option<String>,
    pub user_email: Option<String>,
    pub user_is_admin: bool,
    pub team_scope: Option<String>,
    pub team_name: Option<String>,
    pub auth_method: Option<String>,
    pub session_id: Option<String>,
}

/// Initialize the Rust runtime tracing subscriber and OTEL exporter.
///
/// # Errors
///
/// Returns an error when OTEL exporter configuration is invalid or when the
/// global tracing subscriber cannot be initialized.
pub fn init_tracing(log_filter: &str) -> Result<ObservabilityHandle, String> {
    let config = ObservabilityConfig::from_env()?;
    let _ = OBSERVABILITY_CONFIG.set(config.clone());
    global::set_text_map_propagator(TraceContextPropagator::new());

    let fmt_layer = tracing_subscriber::fmt::layer()
        .with_target(false)
        .compact()
        .with_filter(EnvFilter::new(log_filter));

    if !config.enabled {
        Registry::default()
            .with(fmt_layer)
            .try_init()
            .map_err(|err| format!("failed to initialize tracing subscriber: {err}"))?;
        return Ok(ObservabilityHandle::disabled());
    }

    let provider = build_tracer_provider(&config)?;
    let tracer = provider.tracer("contextforge-rust-runtime");
    let otel_filter =
        filter::filter_fn(|metadata| metadata.is_span() && metadata.target() == OTEL_SPAN_TARGET);
    let subscriber = Registry::default()
        .with(fmt_layer)
        .with(otel_layer().with_tracer(tracer).with_filter(otel_filter));
    subscriber
        .try_init()
        .map_err(|err| format!("failed to initialize tracing subscriber: {err}"))?;

    global::set_tracer_provider(provider.clone());
    let _ = TRACER_PROVIDER.set(provider.clone());
    Ok(ObservabilityHandle {
        provider: Some(provider),
    })
}

#[must_use]
pub fn observability_enabled() -> bool {
    config().enabled
}

#[must_use]
pub fn is_input_capture_enabled(span_name: &str) -> bool {
    config().capture_input_spans.contains(span_name)
}

#[must_use]
pub fn is_output_capture_enabled(span_name: &str) -> bool {
    config().capture_output_spans.contains(span_name)
}

pub(crate) fn trace_request_context(
    incoming_headers: &HeaderMap,
    auth_context: Option<&InternalAuthContext>,
) -> TraceRequestContext {
    let correlation_id = correlation_id_from_headers(incoming_headers);
    let request_id = request_id_from_headers(incoming_headers).or_else(|| correlation_id.clone());

    let Some(auth_context) = auth_context else {
        return TraceRequestContext {
            correlation_id,
            request_id,
            session_id: session_id_from_headers(incoming_headers),
            ..TraceRequestContext::default()
        };
    };

    TraceRequestContext {
        correlation_id,
        request_id,
        user_email: auth_context.email.clone(),
        user_is_admin: auth_context
            .permission_is_admin
            .unwrap_or(auth_context.is_admin),
        team_scope: Some(format_trace_team_scope(auth_context.teams.as_ref())),
        team_name: auth_context.team_name.clone(),
        auth_method: auth_context.auth_method.clone(),
        session_id: session_id_from_headers(incoming_headers),
    }
}

#[must_use]
pub fn start_root_span(name: &'static str, context: &TraceRequestContext) -> Span {
    start_span(name, context, true)
}

#[must_use]
pub fn start_child_span(name: &'static str, context: &TraceRequestContext) -> Span {
    start_span(name, context, false)
}

pub fn set_langfuse_trace_name(span: &Span, value: impl Into<String>) {
    if !config().emit_langfuse_attributes || span.is_none() {
        return;
    }
    set_span_attribute(span, "langfuse.trace.name", value.into());
}

pub fn set_span_attribute(span: &Span, key: &str, value: impl Into<TraceAttributeValue>) {
    if span.is_none() || !should_emit_span_attribute(key) {
        return;
    }

    match sanitize_attribute_value(key, value.into()) {
        SanitizedAttributeValue::Skip => {}
        SanitizedAttributeValue::Bool(value) => span.set_attribute(key.to_string(), value),
        SanitizedAttributeValue::I64(value) => span.set_attribute(key.to_string(), value),
        SanitizedAttributeValue::F64(value) => span.set_attribute(key.to_string(), value),
        SanitizedAttributeValue::String(value) => span.set_attribute(key.to_string(), value),
        SanitizedAttributeValue::StringArray(value) => {
            span.context().span().set_attribute(KeyValue::new(
                key.to_string(),
                opentelemetry::Value::Array(Array::from(
                    value.into_iter().map(StringValue::from).collect::<Vec<_>>(),
                )),
            ));
        }
    }
}

pub fn set_span_error(span: &Span, error: impl AsRef<str>, exc_type: Option<&str>) {
    if span.is_none() {
        return;
    }

    let message = sanitize_trace_text(error.as_ref());
    let bounded = if message.len() <= MAX_EXCEPTION_MESSAGE_LENGTH {
        message
    } else {
        let truncated_length = MAX_EXCEPTION_MESSAGE_LENGTH.saturating_sub(3);
        format!("{}...", &message[..truncated_length])
    };

    span.add_event(
        "exception",
        vec![
            KeyValue::new("exception.type", exc_type.unwrap_or("Error").to_string()),
            KeyValue::new("exception.message", bounded.clone()),
            KeyValue::new("exception.escaped", true),
        ],
    );
    span.set_status(Status::error(bounded.clone()));
    set_span_attribute(span, "error", true);
    if let Some(exc_type) = exc_type {
        set_span_attribute(span, "error.type", exc_type.to_string());
    }
    set_span_attribute(span, "error.message", bounded.clone());
    set_span_attribute(span, "langfuse.observation.level", "ERROR");
    set_span_attribute(span, "langfuse.observation.status_message", bounded);
}

#[must_use]
pub fn serialize_trace_payload(payload: &Value) -> String {
    let redacted = redact_sensitive_fields(payload);
    safe_serialize(&redacted, config().max_trace_payload_size)
}

pub fn inject_current_trace_context(headers: &mut reqwest::header::HeaderMap) {
    if !observability_enabled() {
        return;
    }

    global::get_text_map_propagator(|propagator| {
        propagator.inject_context(&Span::current().context(), &mut HeaderInjector(headers));
    });
}

#[must_use]
pub fn derive_langfuse_trace_name(span_name: &str, attributes: &[(&str, String)]) -> String {
    let mut attr_map = HashMap::new();
    for (key, value) in attributes {
        attr_map.insert(*key, value.clone());
    }

    match span_name {
        "tool.invoke" => attr_map.get("tool.name").map_or_else(
            || span_name.to_string(),
            |tool_name| format!("Tool: {}", sanitize_trace_text(tool_name)),
        ),
        "tool.list" => "Tools".to_string(),
        "prompt.render" => attr_map.get("prompt.id").map_or_else(
            || span_name.to_string(),
            |prompt_id| format!("Prompt: {}", sanitize_trace_text(prompt_id)),
        ),
        "prompt.list" => "Prompts".to_string(),
        "resource.read" => attr_map.get("resource.uri").map_or_else(
            || span_name.to_string(),
            |uri| format!("Resource: {}", sanitize_trace_text(uri)),
        ),
        "resource.list" => "Resources".to_string(),
        "resource_template.list" => "Resource Templates".to_string(),
        "root.list" => "Roots".to_string(),
        _ => span_name.to_string(),
    }
}

#[derive(Debug, Clone)]
pub enum TraceAttributeValue {
    Bool(bool),
    I64(i64),
    F64(f64),
    String(String),
    StringArray(Vec<String>),
    Null,
}

#[derive(Debug, Clone)]
enum SanitizedAttributeValue {
    Skip,
    Bool(bool),
    I64(i64),
    F64(f64),
    String(String),
    StringArray(Vec<String>),
}

impl From<bool> for TraceAttributeValue {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i64> for TraceAttributeValue {
    fn from(value: i64) -> Self {
        Self::I64(value)
    }
}

impl From<i32> for TraceAttributeValue {
    fn from(value: i32) -> Self {
        Self::I64(i64::from(value))
    }
}

impl From<u64> for TraceAttributeValue {
    fn from(value: u64) -> Self {
        Self::I64(i64::try_from(value).unwrap_or(i64::MAX))
    }
}

impl From<usize> for TraceAttributeValue {
    fn from(value: usize) -> Self {
        Self::I64(i64::try_from(value).unwrap_or(i64::MAX))
    }
}

impl From<f64> for TraceAttributeValue {
    fn from(value: f64) -> Self {
        Self::F64(value)
    }
}

impl From<String> for TraceAttributeValue {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<&str> for TraceAttributeValue {
    fn from(value: &str) -> Self {
        Self::String(value.to_string())
    }
}

impl From<Vec<String>> for TraceAttributeValue {
    fn from(value: Vec<String>) -> Self {
        Self::StringArray(value)
    }
}

impl From<Option<String>> for TraceAttributeValue {
    fn from(value: Option<String>) -> Self {
        match value {
            Some(value) => Self::String(value),
            None => Self::Null,
        }
    }
}

impl From<Option<&str>> for TraceAttributeValue {
    fn from(value: Option<&str>) -> Self {
        match value {
            Some(value) => Self::String(value.to_string()),
            None => Self::Null,
        }
    }
}

fn build_tracer_provider(config: &ObservabilityConfig) -> Result<SdkTracerProvider, String> {
    let mut resource_attrs = vec![
        KeyValue::new("service.name", config.service_name.clone()),
        KeyValue::new("service.version", env!("CARGO_PKG_VERSION").to_string()),
        KeyValue::new("deployment.environment", config.deployment_env.clone()),
    ];

    for (key, value) in &config.resource_attributes {
        resource_attrs.push(KeyValue::new(key.clone(), value.clone()));
    }

    let resource = Resource::builder_empty()
        .with_attributes(resource_attrs)
        .build();

    let exporter = build_otlp_exporter(config)?;
    let batch_processor = AsyncBatchSpanProcessor::builder(exporter, runtime::Tokio)
        .with_batch_config(BatchConfigBuilder::default().build())
        .build();
    Ok(SdkTracerProvider::builder()
        .with_resource(resource)
        .with_span_processor(batch_processor)
        .build())
}

fn build_otlp_exporter(config: &ObservabilityConfig) -> Result<SpanExporter, String> {
    let endpoint = config
        .otlp_endpoint
        .clone()
        .ok_or_else(|| "OTLP endpoint not configured".to_string())?;
    let protocol = if is_langfuse_otlp_endpoint(Some(endpoint.as_str())) {
        "http"
    } else {
        config.otlp_protocol.as_str()
    };

    match protocol {
        "grpc" => {
            let mut metadata = MetadataMap::new();
            for (key, value) in &config.otlp_headers {
                let metadata_key = key
                    .parse::<tonic::metadata::MetadataKey<_>>()
                    .map_err(|err| format!("invalid OTLP metadata key '{key}': {err}"))?;
                let metadata_value = MetadataValue::try_from(value.as_str())
                    .map_err(|err| format!("invalid OTLP metadata value for '{key}': {err}"))?;
                metadata.insert(metadata_key, metadata_value);
            }

            SpanExporter::builder()
                .with_tonic()
                .with_endpoint(endpoint)
                .with_metadata(metadata)
                .build()
                .map_err(|err| format!("failed to build OTLP gRPC exporter: {err}"))
        }
        _ => {
            let http_client = reqwest::Client::builder()
                .build()
                .map_err(|err| format!("failed to build OTLP HTTP client: {err}"))?;

            SpanExporter::builder()
                .with_http()
                .with_http_client(http_client)
                .with_endpoint(normalize_http_otlp_endpoint(&endpoint))
                .with_protocol(Protocol::HttpBinary)
                .with_headers(config.otlp_headers.clone())
                .build()
                .map_err(|err| format!("failed to build OTLP HTTP exporter: {err}"))
        }
    }
}

fn normalize_http_otlp_endpoint(endpoint: &str) -> String {
    if endpoint.ends_with("/v1/traces") {
        endpoint.to_string()
    } else if endpoint.ends_with('/') {
        format!("{endpoint}v1/traces")
    } else if endpoint.contains(":4317") {
        format!("{}/v1/traces", endpoint.replace(":4317", ":4318"))
    } else {
        format!("{endpoint}/v1/traces")
    }
}

struct HeaderInjector<'a>(&'a mut reqwest::header::HeaderMap);

impl Injector for HeaderInjector<'_> {
    fn set(&mut self, key: &str, value: String) {
        let Ok(name) = reqwest::header::HeaderName::from_bytes(key.as_bytes()) else {
            return;
        };
        let Ok(value) = reqwest::header::HeaderValue::from_str(&value) else {
            return;
        };
        self.0.insert(name, value);
    }
}

fn start_span(
    name: &'static str,
    context: &TraceRequestContext,
    include_trace_metadata: bool,
) -> Span {
    if !observability_enabled() {
        return Span::none();
    }

    let span = span!(
        target: OTEL_SPAN_TARGET,
        tracing::Level::INFO,
        "contextforge.mcp",
        "mcp.operation" = name
    );
    span.context().span().update_name(name);

    if let Some(correlation_id) = &context.correlation_id {
        set_span_attribute(&span, "correlation_id", correlation_id.clone());
    }
    if let Some(request_id) = &context.request_id {
        set_span_attribute(&span, "request_id", request_id.clone());
    }

    if !include_trace_metadata {
        return span;
    }

    if config().capture_identity_attributes {
        if let Some(user_email) = &context.user_email {
            set_span_attribute(&span, "user.email", user_email.clone());
        }
        if context.user_email.is_some() || context.user_is_admin {
            set_span_attribute(&span, "user.is_admin", context.user_is_admin);
        }
        if let Some(team_scope) = &context.team_scope {
            set_span_attribute(&span, "team.scope", team_scope.clone());
        }
        if let Some(team_name) = &context.team_name {
            set_span_attribute(&span, "team.name", team_name.clone());
        }
    }

    if let Some(auth_method) = &context.auth_method {
        // pragma: allowlist secret
        set_span_attribute(&span, "auth.method", auth_method.clone());
    }

    if config().emit_langfuse_attributes {
        if config().capture_identity_attributes {
            if let Some(user_email) = &context.user_email {
                set_span_attribute(&span, "langfuse.user.id", user_email.clone());
            }
        }
        if let Some(session_id) = &context.session_id {
            set_span_attribute(&span, "langfuse.session.id", session_id.clone());
        }
        set_span_attribute(
            &span,
            "langfuse.environment",
            config().deployment_env.clone(),
        );
        let tags = derive_langfuse_tags(context);
        if !tags.is_empty() {
            set_span_attribute(&span, "langfuse.trace.tags", tags);
        }
        set_langfuse_trace_name(&span, derive_langfuse_trace_name(name, &[]));
        set_span_attribute(&span, "langfuse.observation.level", "DEFAULT");
    }

    span
}

fn derive_langfuse_tags(context: &TraceRequestContext) -> Vec<String> {
    let mut tags = Vec::new();
    if config().capture_identity_attributes {
        if let Some(primary_team) = primary_team_from_scope(context.team_scope.as_deref()) {
            tags.push(format!("team:{primary_team}"));
        }
    }
    // pragma: allowlist secret
    if let Some(auth_method) = &context.auth_method {
        tags.push(format!("auth:{auth_method}"));
    }
    if !config().deployment_env.is_empty() {
        tags.push(format!("env:{}", config().deployment_env));
    }
    tags
}

fn should_emit_span_attribute(attribute_name: &str) -> bool {
    if attribute_name.starts_with("langfuse.") && !config().emit_langfuse_attributes {
        return false;
    }
    if matches!(
        attribute_name,
        "user.email" | "user.is_admin" | "team.scope" | "team.name" | "langfuse.user.id"
    ) && !config().capture_identity_attributes
    {
        return false;
    }
    true
}

fn sanitize_attribute_value(key: &str, value: TraceAttributeValue) -> SanitizedAttributeValue {
    let normalized = normalize_field_name(key);
    if config().redact_fields.contains(&normalized) {
        return SanitizedAttributeValue::String("***".to_string());
    }

    match value {
        TraceAttributeValue::Bool(value) => SanitizedAttributeValue::Bool(value),
        TraceAttributeValue::I64(value) => SanitizedAttributeValue::I64(value),
        TraceAttributeValue::F64(value) => SanitizedAttributeValue::F64(value),
        TraceAttributeValue::String(value) => {
            SanitizedAttributeValue::String(sanitize_trace_scalar(key, &value))
        }
        TraceAttributeValue::StringArray(values) => SanitizedAttributeValue::StringArray(
            values
                .into_iter()
                .map(|value| sanitize_trace_scalar(key, &value))
                .collect(),
        ),
        TraceAttributeValue::Null => SanitizedAttributeValue::Skip,
    }
}

fn sanitize_trace_scalar(field_name: &str, value: &str) -> String {
    if field_looks_like_url(field_name) {
        sanitize_url_for_logging(value)
    } else {
        sanitize_trace_text(value)
    }
}

fn redact_sensitive_fields(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut redacted = Map::new();
            for (key, value) in map {
                if config().redact_fields.contains(&normalize_field_name(key)) {
                    redacted.insert(key.clone(), Value::String("***".to_string()));
                } else {
                    redacted.insert(key.clone(), sanitize_trace_value(key, value));
                }
            }
            Value::Object(redacted)
        }
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| sanitize_trace_value("item", item))
                .collect(),
        ),
        Value::String(text) => Value::String(sanitize_trace_text(text)),
        _ => value.clone(),
    }
}

fn sanitize_trace_value(field_name: &str, value: &Value) -> Value {
    match value {
        Value::Object(_) => redact_sensitive_fields(value),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| sanitize_trace_value(field_name, item))
                .collect(),
        ),
        Value::String(text) => Value::String(sanitize_trace_scalar(field_name, text)),
        _ => value.clone(),
    }
}

fn safe_serialize(value: &Value, max_size: usize) -> String {
    let mut writer = BoundedPreviewWriter::new(max_size);
    if serde_json::to_writer(&mut writer, value).is_err() {
        return r#"{"_error":"serialization_failed"}"#.to_string();
    }

    let total_size = writer.total_size();
    let preview = writer.preview();

    if total_size <= max_size {
        return preview;
    }

    let mut wrapped = json!({
        "_truncated": true,
        "_original_size": total_size,
        "_preview": preview,
    })
    .to_string();

    let mut preview = preview;
    while wrapped.len() > max_size && !preview.is_empty() {
        let overflow = wrapped.len().saturating_sub(max_size);
        let trim_amount = overflow.max(1);
        let new_len = preview.len().saturating_sub(trim_amount);
        preview.truncate(new_len);
        wrapped = json!({
            "_truncated": true,
            "_original_size": total_size,
            "_preview": preview,
        })
        .to_string();
    }

    if wrapped.len() <= max_size {
        return wrapped;
    }

    let minimal = r#"{"_truncated":true}"#;
    minimal.chars().take(max_size).collect()
}

#[derive(Debug, Default)]
struct BoundedPreviewWriter {
    preview: Vec<u8>,
    total_size: usize,
    max_size: usize,
}

impl BoundedPreviewWriter {
    fn new(max_size: usize) -> Self {
        Self {
            preview: Vec::with_capacity(max_size),
            total_size: 0,
            max_size,
        }
    }

    fn total_size(&self) -> usize {
        self.total_size
    }

    fn preview(&self) -> String {
        String::from_utf8_lossy(&self.preview).into_owned()
    }
}

impl io::Write for BoundedPreviewWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.total_size += buf.len();
        if self.preview.len() < self.max_size {
            let remaining = self.max_size - self.preview.len();
            self.preview
                .extend_from_slice(&buf[..buf.len().min(remaining)]);
        }
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn normalize_field_name(value: &str) -> String {
    value
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .flat_map(char::to_lowercase)
        .collect()
}

fn field_looks_like_url(field_name: &str) -> bool {
    let normalized = normalize_field_name(field_name);
    normalized.ends_with("url") || normalized.ends_with("uri") || normalized.ends_with("endpoint")
}

fn sanitize_trace_text(text: &str) -> String {
    let mut sanitized = sanitize_exception_message(text);
    let may_have_credentials = contains_ascii_case_insensitive(&sanitized, "bearer") // pragma: allowlist secret
        || contains_ascii_case_insensitive(&sanitized, "basic");
    if may_have_credentials {
        sanitized = bearer_regex()
            .replace_all(&sanitized, |captures: &regex::Captures<'_>| {
                format!("{} ***{}", &captures[1], &captures[3])
            })
            .to_string();
    }

    if sanitized.contains('=') || sanitized.contains(':') {
        for pattern in &config().text_redaction_patterns {
            sanitized = pattern
                .quoted
                .replace_all(&sanitized, "$1***$3")
                .to_string();
            sanitized = pattern
                .bare
                .replace_all(&sanitized, |captures: &regex::Captures<'_>| {
                    let value = &captures[2];
                    if value.eq_ignore_ascii_case("REDACTED") || value == "***" {
                        format!("{}{}", &captures[1], value)
                    } else {
                        format!("{}***", &captures[1])
                    }
                })
                .to_string();
        }
    }

    if sanitized.contains("*** ") {
        repeated_redaction_regex()
            .replace_all(&sanitized, "***")
            .to_string()
    } else {
        sanitized
    }
}

fn field_name_text_pattern(field_name: &str) -> String {
    let parts = field_name
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|part| !part.is_empty())
        .map(regex::escape)
        .collect::<Vec<_>>();
    if parts.is_empty() {
        regex::escape(field_name)
    } else {
        parts.join(r"[\W_]*")
    }
}

fn sanitize_exception_message(message: &str) -> String {
    if message.is_empty() {
        return message.to_string();
    }
    if !message.contains("http://") && !message.contains("https://") {
        return message.to_string();
    }

    url_regex()
        .replace_all(message, |captures: &regex::Captures<'_>| {
            sanitize_url_for_logging(&captures[0])
        })
        .to_string()
}

fn sanitize_url_for_logging(url: &str) -> String {
    let Ok(mut parsed) = url::Url::parse(url) else {
        return url.to_string();
    };

    if !parsed.username().is_empty() || parsed.password().is_some() {
        let _ = parsed.set_username(URL_REDACTED);
        let _ = parsed.set_password(Some(URL_REDACTED));
    }

    if parsed.query().is_none() {
        return parsed.to_string();
    }

    let sensitive_names = static_sensitive_params()
        .iter()
        .cloned()
        .chain(
            config()
                .raw_redact_fields
                .iter()
                .map(|value| value.to_lowercase()),
        )
        .collect::<HashSet<_>>();

    let sanitized_query = parsed
        .query_pairs()
        .map(|(key, value)| {
            let normalized_key = key.to_string().to_lowercase();
            if sensitive_names.contains(&normalized_key) {
                (Cow::Owned(key.to_string()), Cow::Borrowed(URL_REDACTED))
            } else {
                (Cow::Owned(key.to_string()), Cow::Owned(value.to_string()))
            }
        })
        .collect::<Vec<_>>();

    parsed
        .query_pairs_mut()
        .clear()
        .extend_pairs(sanitized_query);
    parsed.to_string()
}

fn static_sensitive_params() -> &'static HashSet<String> {
    STATIC_SENSITIVE_PARAMS.get_or_init(|| {
        [
            "api_key",
            "apikey",
            "api-key",
            "key",
            "token",
            "access_token",
            "auth",
            "auth_token",
            "secret",
            "password",
            "pwd",
            "credential",
            "credentials",
            "tavilyapikey",
            "tavilyApiKey",
        ]
        .into_iter()
        .map(str::to_lowercase)
        .collect()
    })
}

fn url_regex() -> &'static Regex {
    URL_REGEX.get_or_init(|| Regex::new(r#"https?://[^\s<>"']+"#).expect("valid url regex"))
}

fn bearer_regex() -> &'static Regex {
    BEARER_REGEX.get_or_init(|| {
        Regex::new(r#"(?i)\b(Bearer|Basic)\s+([A-Za-z0-9._~+/=-]+)([\s,;'"]|$)"#)
            .expect("valid bearer regex")
    })
}

fn repeated_redaction_regex() -> &'static Regex {
    REPEATED_REDACTION_REGEX.get_or_init(|| {
        Regex::new(r"\*\*\*(?:\s+\*\*\*)+").expect("valid repeated redaction regex")
    })
}

fn contains_ascii_case_insensitive(haystack: &str, needle: &str) -> bool {
    if needle.is_empty() || haystack.len() < needle.len() {
        return false;
    }

    haystack
        .as_bytes()
        .windows(needle.len())
        .any(|window| window.eq_ignore_ascii_case(needle.as_bytes()))
}

fn build_text_redaction_patterns(raw_redact_fields: &[String]) -> Vec<TextRedactionPattern> {
    raw_redact_fields
        .iter()
        .map(|field_name| {
            let key_pattern = field_name_text_pattern(field_name);
            TextRedactionPattern {
                quoted: Regex::new(&format!(
                    r#"(?i)(\b{key_pattern}\b\s*(?:=|:)\s*['"])([^'"]*)(['"])"#
                ))
                .expect("valid quoted field redaction regex"),
                bare: Regex::new(&format!(r"(?i)(\b{key_pattern}\b\s*(?:=|:)\s*)([^\s,;]+)"))
                    .expect("valid bare field redaction regex"),
            }
        })
        .collect()
}

fn session_id_from_headers(headers: &HeaderMap) -> Option<String> {
    headers
        .get("mcp-session-id")
        .or_else(|| headers.get("x-mcp-session-id"))
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn correlation_id_from_headers(headers: &HeaderMap) -> Option<String> {
    headers
        .get("x-correlation-id")
        .or_else(|| headers.get("correlation-id"))
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn request_id_from_headers(headers: &HeaderMap) -> Option<String> {
    headers
        .get("x-request-id")
        .or_else(|| headers.get("request-id"))
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn format_trace_team_scope(token_teams: Option<&Vec<String>>) -> String {
    let Some(token_teams) = token_teams else {
        return "admin".to_string();
    };

    let normalized = token_teams
        .iter()
        .map(|team| team.trim())
        .filter(|team| !team.is_empty())
        .map(str::to_string)
        .collect::<Vec<_>>();

    if normalized.is_empty() {
        return "public".to_string();
    }

    if normalized.len() <= 5 {
        return normalized.join(TEAM_SCOPE_SEPARATOR);
    }

    let mut limited = normalized.into_iter().take(5).collect::<Vec<_>>();
    limited.push(ELLIPSIS_MARKER.to_string());
    limited.join(TEAM_SCOPE_SEPARATOR)
}

fn primary_team_from_scope(team_scope: Option<&str>) -> Option<String> {
    let team_scope = team_scope?;
    if team_scope.is_empty() || matches!(team_scope, "admin" | "public") {
        return None;
    }

    team_scope
        .split(',')
        .map(str::trim)
        .find(|value| !value.is_empty() && *value != ELLIPSIS_MARKER)
        .map(str::to_string)
}

fn parse_optional_bool(name: &str) -> Option<bool> {
    std::env::var(name)
        .ok()
        .and_then(|value| match value.trim().to_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Some(true),
            "0" | "false" | "no" | "off" => Some(false),
            _ => None,
        })
}

fn parse_bool_with_default(name: &str, default: bool) -> bool {
    parse_optional_bool(name).unwrap_or(default)
}

fn parse_csv_set(value: &str) -> HashSet<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .collect()
}

fn parse_resource_attributes(value: &str) -> Vec<(String, String)> {
    value
        .split(',')
        .filter_map(|item| item.split_once('='))
        .map(|(key, value)| (key.trim().to_string(), value.trim().to_string()))
        .filter(|(key, _)| !key.is_empty())
        .collect()
}

fn parse_otlp_headers(value: &str) -> HashMap<String, String> {
    value
        .split(',')
        .filter_map(|item| item.split_once('='))
        .map(|(key, value)| (key.trim().to_string(), value.trim().to_string()))
        .filter(|(key, _)| !key.is_empty())
        .collect()
}

fn get_header_case_insensitive<'a>(
    headers: &'a HashMap<String, String>,
    name: &str,
) -> Option<&'a str> {
    let normalized_name = name.to_lowercase();
    headers
        .iter()
        .find(|(key, _)| key.to_lowercase() == normalized_name)
        .map(|(_, value)| value.as_str())
}

fn set_header_case_insensitive(headers: &mut HashMap<String, String>, name: &str, value: String) {
    let normalized_name = name.to_lowercase();
    if let Some(existing_key) = headers
        .keys()
        .find(|key| key.to_lowercase() == normalized_name)
        .cloned()
    {
        headers.insert(existing_key, value);
    } else {
        headers.insert(name.to_string(), value);
    }
}

fn is_langfuse_otlp_endpoint(endpoint: Option<&str>) -> bool {
    endpoint.is_some_and(|value| value.contains(LANGFUSE_OTEL_PATH_FRAGMENT))
}

fn resolve_langfuse_basic_auth() -> String {
    if let Ok(explicit_auth) = std::env::var("LANGFUSE_OTEL_AUTH")
        && !explicit_auth.trim().is_empty()
    {
        return explicit_auth.trim().to_string();
    }

    let public_key = std::env::var("LANGFUSE_PUBLIC_KEY").unwrap_or_default();
    let secret_key = std::env::var("LANGFUSE_SECRET_KEY").unwrap_or_default();
    if public_key.trim().is_empty() || secret_key.trim().is_empty() {
        return String::new();
    }

    STANDARD.encode(format!("{}:{}", public_key.trim(), secret_key.trim()))
}

fn resolve_otlp_endpoint() -> Option<String> {
    std::env::var("LANGFUSE_OTEL_ENDPOINT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
}

fn resolve_otlp_headers(endpoint: Option<&str>) -> HashMap<String, String> {
    let mut headers = std::env::var("OTEL_EXPORTER_OTLP_HEADERS")
        .ok()
        .map(|value| parse_otlp_headers(&value))
        .unwrap_or_default();

    if is_langfuse_otlp_endpoint(endpoint) {
        let basic_auth = resolve_langfuse_basic_auth();
        if !basic_auth.is_empty()
            && get_header_case_insensitive(&headers, "Authorization").is_none()
        {
            set_header_case_insensitive(
                &mut headers,
                "Authorization",
                format!("Basic {basic_auth}"),
            );
        }
    }

    headers
}

fn validate_langfuse_configuration(
    endpoint: Option<&str>,
    headers: &HashMap<String, String>,
) -> Result<(), String> {
    if !is_langfuse_otlp_endpoint(endpoint) {
        return Ok(());
    }

    let Some(authorization) = get_header_case_insensitive(headers, "Authorization") else {
        return Err(
            "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string(),
        );
    };

    let mut parts = authorization.split_whitespace();
    let scheme = parts.next().unwrap_or_default();
    let encoded = parts.next().unwrap_or_default();
    if !scheme.eq_ignore_ascii_case("basic") {
        return Err(
            "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string(),
        );
    }

    let decoded = STANDARD
        .decode(encoded.trim())
        .map_err(|_| {
            "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string()
        })
        .and_then(|bytes| {
            String::from_utf8(bytes).map_err(|_| {
                "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string()
            })
        })?;
    let Some((public_key, secret_key)) = decoded.split_once(':') else {
        return Err(
            "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string(),
        );
    };

    if public_key.trim().is_empty() || secret_key.trim().is_empty() {
        return Err(
            "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.".to_string(),
        );
    }

    Ok(())
}

fn config() -> &'static ObservabilityConfig {
    OBSERVABILITY_CONFIG.get_or_init(|| {
        ObservabilityConfig::from_env().unwrap_or_else(|_| ObservabilityConfig {
            enabled: false,
            deployment_env: "development".to_string(),
            service_name: "mcp-gateway".to_string(),
            resource_attributes: Vec::new(),
            otlp_endpoint: None,
            otlp_protocol: "grpc".to_string(),
            otlp_headers: HashMap::new(),
            emit_langfuse_attributes: false,
            capture_identity_attributes: false,
            redact_fields: parse_csv_set(DEFAULT_REDACT_FIELDS)
                .into_iter()
                .map(|value| normalize_field_name(&value))
                .collect(),
            raw_redact_fields: DEFAULT_REDACT_FIELDS
                .split(',')
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .collect(),
            text_redaction_patterns: build_text_redaction_patterns(
                &DEFAULT_REDACT_FIELDS
                    .split(',')
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .map(str::to_string)
                    .collect::<Vec<_>>(),
            ),
            max_trace_payload_size: DEFAULT_MAX_PAYLOAD_SIZE,
            capture_input_spans: HashSet::new(),
            capture_output_spans: HashSet::new(),
        })
    })
}

impl ObservabilityConfig {
    fn from_env() -> Result<Self, String> {
        let enabled = parse_bool_with_default("OTEL_ENABLE_OBSERVABILITY", false);
        let otlp_endpoint = resolve_otlp_endpoint();
        let otlp_headers = resolve_otlp_headers(otlp_endpoint.as_deref());
        if enabled {
            validate_langfuse_configuration(otlp_endpoint.as_deref(), &otlp_headers)?;
        }

        let emit_langfuse_attributes = parse_optional_bool("OTEL_EMIT_LANGFUSE_ATTRIBUTES")
            .unwrap_or_else(|| is_langfuse_otlp_endpoint(otlp_endpoint.as_deref()));
        let capture_identity_attributes = parse_optional_bool("OTEL_CAPTURE_IDENTITY_ATTRIBUTES")
            .unwrap_or(emit_langfuse_attributes);

        let raw_redact_fields = std::env::var("OTEL_REDACT_FIELDS")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| DEFAULT_REDACT_FIELDS.to_string())
            .split(',')
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_string)
            .collect::<Vec<_>>();

        Ok(Self {
            enabled,
            deployment_env: std::env::var("DEPLOYMENT_ENV")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .or_else(|| {
                    std::env::var("ENVIRONMENT")
                        .ok()
                        .filter(|value| !value.trim().is_empty())
                })
                .unwrap_or_else(|| "development".to_string()),
            service_name: std::env::var("OTEL_SERVICE_NAME")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "mcp-gateway".to_string()),
            resource_attributes: std::env::var("OTEL_RESOURCE_ATTRIBUTES")
                .ok()
                .map(|value| parse_resource_attributes(&value))
                .unwrap_or_default(),
            otlp_endpoint,
            otlp_protocol: std::env::var("OTEL_EXPORTER_OTLP_PROTOCOL")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "grpc".to_string())
                .to_lowercase(),
            otlp_headers,
            emit_langfuse_attributes,
            capture_identity_attributes,
            redact_fields: raw_redact_fields
                .iter()
                .map(|value| normalize_field_name(value))
                .collect(),
            text_redaction_patterns: build_text_redaction_patterns(&raw_redact_fields),
            raw_redact_fields,
            max_trace_payload_size: std::env::var("OTEL_MAX_TRACE_PAYLOAD_SIZE")
                .ok()
                .and_then(|value| value.parse::<usize>().ok())
                .map_or(DEFAULT_MAX_PAYLOAD_SIZE, |value| value.max(256)),
            capture_input_spans: std::env::var("OTEL_CAPTURE_INPUT_SPANS")
                .ok()
                .map(|value| parse_csv_set(&value))
                .unwrap_or_default(),
            capture_output_spans: std::env::var("OTEL_CAPTURE_OUTPUT_SPANS")
                .ok()
                .map(|value| parse_csv_set(&value))
                .unwrap_or_default(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{
        TraceAttributeValue, correlation_id_from_headers, derive_langfuse_trace_name,
        normalize_http_otlp_endpoint, redact_sensitive_fields, request_id_from_headers,
        sanitize_trace_text, sanitize_url_for_logging, serialize_trace_payload,
        trace_request_context, validate_langfuse_configuration,
    };
    use crate::InternalAuthContext;
    use axum::http::{HeaderMap, HeaderValue};
    use serde_json::{Value, json};
    use std::collections::HashMap;

    #[test]
    fn sanitize_url_redacts_sensitive_query_values() {
        let sanitized =
            sanitize_url_for_logging("https://api.example.com/path?token=secret&q=test");
        assert!(sanitized.contains("token=REDACTED"));
        assert!(sanitized.contains("q=test"));
        assert!(!sanitized.contains("secret"));
    }

    #[test]
    fn sanitize_trace_text_redacts_embedded_secrets() {
        let sanitized = sanitize_trace_text(
            "failed Bearer abc123 token=secret456 https://x.test?a=1&token=urlsecret",
        );
        assert!(!sanitized.contains("abc123"));
        assert!(!sanitized.contains("secret456"));
        assert!(!sanitized.contains("urlsecret"));
        assert!(sanitized.contains("Bearer ***"));
    }

    #[test]
    fn redact_sensitive_fields_redacts_nested_strings() {
        let payload = json!({
            "messages": ["Bearer abc123", "token=secret456"],
            "resource": {"uri": "https://x.test?a=1&token=urlsecret"}
        });
        let redacted = redact_sensitive_fields(&payload);
        let serialized = serde_json::to_string(&redacted).expect("serialized");
        assert!(!serialized.contains("abc123"));
        assert!(!serialized.contains("secret456"));
        assert!(!serialized.contains("urlsecret"));
    }

    #[test]
    fn serialize_trace_payload_bounds_large_json() {
        let payload = json!({
            "value": "x".repeat(2048),
        });
        let serialized = serialize_trace_payload(&payload);
        assert!(!serialized.is_empty());
        assert!(serialized.len() <= super::DEFAULT_MAX_PAYLOAD_SIZE);
    }

    #[test]
    fn serialize_trace_payload_sanitizes_top_level_string_content() {
        let serialized = serialize_trace_payload(&Value::String(
            "Bearer abc123 https://x.test/path?token=secret456".to_string(),
        ));
        assert!(!serialized.contains("abc123"));
        assert!(!serialized.contains("secret456"));
        assert!(serialized.contains("Bearer ***"));
        assert!(serialized.contains("token=REDACTED"));
    }

    #[test]
    fn derive_trace_names_match_python_conventions() {
        assert_eq!(
            derive_langfuse_trace_name(
                "tool.invoke",
                &[("tool.name", "fast-time-get-system-time".to_string())],
            ),
            "Tool: fast-time-get-system-time"
        );
        assert_eq!(derive_langfuse_trace_name("tool.list", &[]), "Tools");
        assert_eq!(
            derive_langfuse_trace_name(
                "resource.read",
                &[("resource.uri", "time://formats".to_string())],
            ),
            "Resource: time://formats"
        );
    }

    #[test]
    fn normalize_http_otlp_endpoint_adds_v1_traces_suffix() {
        assert_eq!(
            normalize_http_otlp_endpoint("http://collector:4317"),
            "http://collector:4318/v1/traces"
        );
        assert_eq!(
            normalize_http_otlp_endpoint("http://collector:4318"),
            "http://collector:4318/v1/traces"
        );
        assert_eq!(
            normalize_http_otlp_endpoint("http://collector:4318/v1/traces"),
            "http://collector:4318/v1/traces"
        );
    }

    #[test]
    fn validate_langfuse_configuration_requires_basic_auth() {
        let mut headers = HashMap::new();
        headers.insert("Authorization".to_string(), "Basic cGs6c2s=".to_string());
        validate_langfuse_configuration(
            Some("http://langfuse/api/public/otel/v1/traces"),
            &headers,
        )
        .expect("valid auth");

        headers.insert("Authorization".to_string(), "Bearer token".to_string());
        assert!(
            validate_langfuse_configuration(
                Some("http://langfuse/api/public/otel/v1/traces"),
                &headers,
            )
            .is_err()
        );
    }

    #[test]
    fn trace_attribute_value_string_conversion_is_explicit() {
        let value = TraceAttributeValue::from("team-a");
        assert!(matches!(value, TraceAttributeValue::String(_)));
    }

    #[test]
    fn correlation_and_request_ids_are_extracted_from_headers() {
        let mut headers = HeaderMap::new();
        headers.insert("x-correlation-id", HeaderValue::from_static("corr-123"));
        headers.insert("x-request-id", HeaderValue::from_static("req-456"));

        assert_eq!(
            correlation_id_from_headers(&headers).as_deref(),
            Some("corr-123")
        );
        assert_eq!(
            request_id_from_headers(&headers).as_deref(),
            Some("req-456")
        );
    }

    #[test]
    fn trace_request_context_uses_correlation_id_as_request_id_fallback() {
        let mut headers = HeaderMap::new();
        headers.insert("x-correlation-id", HeaderValue::from_static("corr-123"));
        headers.insert("mcp-session-id", HeaderValue::from_static("session-789"));

        let auth_context = InternalAuthContext {
            email: Some("admin@example.com".to_string()),
            teams: Some(vec!["team-a".to_string()]),
            team_name: Some("Team A".to_string()),
            auth_method: Some("jwt".to_string()),
            permission_is_admin: Some(true),
            is_admin: true,
            is_authenticated: true,
        };

        let context = trace_request_context(&headers, Some(&auth_context));
        assert_eq!(context.correlation_id.as_deref(), Some("corr-123"));
        assert_eq!(context.request_id.as_deref(), Some("corr-123"));
        assert_eq!(context.session_id.as_deref(), Some("session-789"));
        assert_eq!(context.user_email.as_deref(), Some("admin@example.com"));
        assert_eq!(context.team_scope.as_deref(), Some("team-a"));
        assert_eq!(context.team_name.as_deref(), Some("Team A"));
        assert_eq!(context.auth_method.as_deref(), Some("jwt"));
        assert!(context.user_is_admin);
    }
}
