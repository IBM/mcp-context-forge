use std::collections::HashMap;
use std::env;
use std::sync::OnceLock;

use opentelemetry::{
    Context, KeyValue, global,
    propagation::Extractor,
    trace::{Span, Status, Tracer},
};
use opentelemetry_otlp::{SpanExporter, WithExportConfig, WithHttpConfig};
use opentelemetry_sdk::{
    Resource,
    propagation::TraceContextPropagator,
    trace::{BatchConfigBuilder, BatchSpanProcessor, SdkTracerProvider},
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

const DEFAULT_SERVICE_NAME: &str = "contextforge-rust-plugin";
const LANGFUSE_OTEL_PATH_FRAGMENT: &str = "/api/public/otel";
const TRACE_CONTEXT_KEY: &str = "traceparent";
const SAFE_PLUGIN_ERROR_MESSAGE: &str = "rust plugin operation failed";

static TELEMETRY_STATE: OnceLock<TelemetryState> = OnceLock::new();

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PluginTraceContext {
    pub traceparent: Option<String>,
    pub trace_id: Option<String>,
    pub parent_span_id: Option<String>,
}

impl PluginTraceContext {
    #[must_use]
    pub fn from_optional_pyany(trace_context: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        match trace_context {
            Some(value) if !value.is_none() => Self::from_pyany(value),
            _ => Ok(Self::default()),
        }
    }

    #[must_use]
    pub fn from_pyany(value: &Bound<'_, PyAny>) -> PyResult<Self> {
        let dict = value.cast::<PyDict>().map_err(|_| {
            PyValueError::new_err(
                "trace_context must be a dict with optional traceparent, trace_id, and parent_span_id fields",
            )
        })?;

        let traceparent = dict
            .get_item("traceparent")?
            .and_then(|item| item.extract::<Option<String>>().ok())
            .flatten();
        let trace_id = dict
            .get_item("trace_id")?
            .and_then(|item| item.extract::<Option<String>>().ok())
            .flatten();
        let parent_span_id = dict
            .get_item("parent_span_id")?
            .and_then(|item| item.extract::<Option<String>>().ok())
            .flatten();

        Ok(Self {
            traceparent,
            trace_id,
            parent_span_id,
        })
    }

    fn carrier(&self) -> HashMap<String, String> {
        let mut carrier = HashMap::new();
        if let Some(traceparent) = &self.traceparent {
            carrier.insert(TRACE_CONTEXT_KEY.to_string(), traceparent.clone());
        }
        carrier
    }
}

pub struct PluginSpanGuard {
    span: Option<global::BoxedSpan>,
    ended: bool,
}

impl PluginSpanGuard {
    #[must_use]
    pub fn disabled() -> Self {
        Self {
            span: None,
            ended: true,
        }
    }

    pub fn mark_ok(&mut self) {
        if let Some(span) = self.span.as_mut() {
            span.set_status(Status::Ok);
            span.end();
            self.ended = true;
        }
    }

    pub fn mark_error(&mut self, message: impl Into<String>) {
        if let Some(span) = self.span.as_mut() {
            let _ = message.into();
            span.set_status(Status::error(SAFE_PLUGIN_ERROR_MESSAGE.to_string()));
            span.set_attribute(KeyValue::new("error", true));
            span.set_attribute(KeyValue::new(
                "exception.message",
                SAFE_PLUGIN_ERROR_MESSAGE,
            ));
            span.end();
            self.ended = true;
        }
    }
}

impl Drop for PluginSpanGuard {
    fn drop(&mut self) {
        if !self.ended {
            if let Some(span) = self.span.as_mut() {
                span.end();
            }
            self.ended = true;
        }
    }
}

#[must_use]
pub fn start_plugin_span(
    plugin_name: &'static str,
    operation: &'static str,
    trace_context: &PluginTraceContext,
) -> PluginSpanGuard {
    let state = TELEMETRY_STATE.get_or_init(TelemetryState::from_env);
    if !state.enabled {
        return PluginSpanGuard::disabled();
    }

    let tracer = global::tracer("contextforge-rust-plugins");
    let parent_context = state.extract_parent_context(trace_context);
    let mut span = tracer.start_with_context(format!("{plugin_name}.{operation}"), &parent_context);
    span.set_attribute(KeyValue::new("plugin.name", plugin_name));
    span.set_attribute(KeyValue::new("plugin.operation", operation));
    span.set_attribute(KeyValue::new("contextforge.runtime", "rust"));
    if let Some(trace_id) = &trace_context.trace_id {
        span.set_attribute(KeyValue::new(
            "contextforge.parent.trace_id",
            trace_id.clone(),
        ));
    }
    if let Some(parent_span_id) = &trace_context.parent_span_id {
        span.set_attribute(KeyValue::new(
            "contextforge.parent.span_id",
            parent_span_id.clone(),
        ));
    }

    PluginSpanGuard {
        span: Some(span),
        ended: false,
    }
}

struct TelemetryState {
    enabled: bool,
    _provider: Option<SdkTracerProvider>,
}

impl TelemetryState {
    fn from_env() -> Self {
        global::set_text_map_propagator(TraceContextPropagator::new());

        if !env_flag("OTEL_ENABLE_OBSERVABILITY") {
            return Self {
                enabled: false,
                _provider: None,
            };
        }

        if !otlp_export_enabled() {
            return Self {
                enabled: false,
                _provider: None,
            };
        }

        let Some(endpoint) = otlp_endpoint() else {
            return Self {
                enabled: false,
                _provider: None,
            };
        };

        if !langfuse_config_valid(&endpoint) {
            return Self {
                enabled: false,
                _provider: None,
            };
        }

        let provider = match build_provider(&endpoint) {
            Ok(provider) => provider,
            Err(_) => {
                return Self {
                    enabled: false,
                    _provider: None,
                };
            }
        };

        global::set_tracer_provider(provider.clone());
        Self {
            enabled: true,
            _provider: Some(provider),
        }
    }

    fn extract_parent_context(&self, trace_context: &PluginTraceContext) -> Context {
        if !self.enabled {
            return Context::new();
        }

        global::get_text_map_propagator(|propagator| {
            propagator.extract(&TraceContextCarrier(trace_context.carrier()))
        })
    }
}

struct TraceContextCarrier(HashMap<String, String>);

impl Extractor for TraceContextCarrier {
    fn get(&self, key: &str) -> Option<&str> {
        self.0.get(key).map(String::as_str)
    }

    fn keys(&self) -> Vec<&str> {
        self.0.keys().map(String::as_str).collect()
    }
}

fn build_provider(endpoint: &str) -> Result<SdkTracerProvider, String> {
    let exporter = build_exporter(endpoint)?;
    let resource = Resource::builder_empty()
        .with_attributes([
            KeyValue::new("service.name", service_name()),
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION").to_string()),
        ])
        .build();

    Ok(SdkTracerProvider::builder()
        .with_resource(resource)
        .with_span_processor(
            BatchSpanProcessor::builder(exporter)
                .with_batch_config(BatchConfigBuilder::default().build())
                .build(),
        )
        .build())
}

fn build_exporter(endpoint: &str) -> Result<SpanExporter, String> {
    let headers = otlp_headers();

    SpanExporter::builder()
        .with_http()
        .with_endpoint(normalize_http_endpoint(endpoint))
        .with_headers(headers)
        .build()
        .map_err(|err| format!("failed to build OTLP HTTP exporter: {err}"))
}

fn env_flag(name: &str) -> bool {
    matches!(
        env::var(name).ok().as_deref(),
        Some("1" | "true" | "TRUE" | "True" | "yes" | "YES" | "on" | "ON")
    )
}

fn otlp_export_enabled() -> bool {
    match env::var("OTEL_TRACES_EXPORTER") {
        Ok(value) => {
            let exporter = value.trim().to_ascii_lowercase();
            exporter.is_empty() || exporter == "otlp"
        }
        Err(_) => true,
    }
}

fn otlp_endpoint() -> Option<String> {
    env::var("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .or_else(|| {
            env::var("LANGFUSE_OTEL_ENDPOINT")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
}

fn otlp_headers() -> HashMap<String, String> {
    let mut headers: HashMap<String, String> = env::var("OTEL_EXPORTER_OTLP_HEADERS")
        .ok()
        .map(|raw| {
            raw.split(',')
                .filter_map(|pair| {
                    let mut parts = pair.splitn(2, '=');
                    let key = parts.next()?.trim();
                    let value = parts.next()?.trim();
                    if key.is_empty() || value.is_empty() {
                        return None;
                    }
                    Some((key.to_string(), value.to_string()))
                })
                .collect()
        })
        .unwrap_or_default();

    if is_langfuse_endpoint(otlp_endpoint().as_deref())
        && !headers
            .keys()
            .any(|key: &String| key.eq_ignore_ascii_case("authorization"))
    {
        if let Some(auth) = resolve_langfuse_basic_auth() {
            headers.insert("Authorization".to_string(), format!("Basic {auth}"));
        }
    }

    headers
}

fn service_name() -> String {
    env::var("OTEL_SERVICE_NAME")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_SERVICE_NAME.to_string())
}

fn normalize_http_endpoint(endpoint: &str) -> String {
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

fn is_langfuse_endpoint(endpoint: Option<&str>) -> bool {
    endpoint
        .map(|value| value.contains(LANGFUSE_OTEL_PATH_FRAGMENT))
        .unwrap_or(false)
}

fn resolve_langfuse_basic_auth() -> Option<String> {
    if let Ok(explicit_auth) = env::var("LANGFUSE_OTEL_AUTH") {
        let trimmed = explicit_auth.trim();
        if !trimmed.is_empty() {
            return Some(trimmed.to_string());
        }
    }

    let public_key = env::var("LANGFUSE_PUBLIC_KEY").ok()?.trim().to_string();
    let secret_key = env::var("LANGFUSE_SECRET_KEY").ok()?.trim().to_string();
    if public_key.is_empty() || secret_key.is_empty() {
        return None;
    }
    Some(base64::Engine::encode(
        &base64::engine::general_purpose::STANDARD,
        format!("{public_key}:{secret_key}"),
    ))
}

fn langfuse_config_valid(endpoint: &str) -> bool {
    if !is_langfuse_endpoint(Some(endpoint)) {
        return true;
    }

    let Some(authorization) = otlp_headers()
        .into_iter()
        .find(|(key, _)| key.eq_ignore_ascii_case("authorization"))
        .map(|(_, value)| value)
    else {
        return false;
    };

    let mut parts = authorization.split_whitespace();
    let scheme = parts.next().unwrap_or_default();
    let encoded = parts.next().unwrap_or_default();
    if !scheme.eq_ignore_ascii_case("basic") {
        return false;
    }

    let Ok(decoded) =
        base64::Engine::decode(&base64::engine::general_purpose::STANDARD, encoded.trim())
    else {
        return false;
    };
    let Ok(decoded) = String::from_utf8(decoded) else {
        return false;
    };
    let Some((public_key, secret_key)) = decoded.split_once(':') else {
        return false;
    };

    !public_key.trim().is_empty() && !secret_key.trim().is_empty()
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDict;
    use std::sync::{Mutex, OnceLock};

    fn with_python<T>(f: impl FnOnce(Python<'_>) -> T) -> T {
        Python::initialize();
        Python::attach(f)
    }

    fn with_env_lock<T>(f: impl FnOnce() -> T) -> T {
        static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        let lock = ENV_LOCK.get_or_init(|| Mutex::new(()));
        let _guard = lock.lock().unwrap();
        f()
    }

    fn with_isolated_env<T>(keys: &[&str], f: impl FnOnce() -> T) -> T {
        with_env_lock(|| {
            let saved: Vec<(String, Option<String>)> = keys
                .iter()
                .map(|key| ((*key).to_string(), std::env::var(key).ok()))
                .collect();
            for key in keys {
                unsafe {
                    std::env::remove_var(key);
                }
            }

            let result = f();

            for (key, value) in saved {
                match value {
                    Some(value) => unsafe {
                        std::env::set_var(&key, value);
                    },
                    None => unsafe {
                        std::env::remove_var(&key);
                    },
                }
            }

            result
        })
    }

    #[test]
    fn normalize_http_endpoint_adds_trace_suffix() {
        assert_eq!(
            normalize_http_endpoint("http://localhost:4318"),
            "http://localhost:4318/v1/traces"
        );
    }

    #[test]
    fn trace_context_defaults_to_empty() {
        assert_eq!(PluginTraceContext::default(), PluginTraceContext::default());
    }

    #[test]
    fn trace_context_parses_python_dict() {
        with_python(|py| {
            let dict = PyDict::new(py);
            dict.set_item(
                "traceparent",
                "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            )
            .unwrap();
            dict.set_item("trace_id", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                .unwrap();
            dict.set_item("parent_span_id", "bbbbbbbbbbbbbbbb").unwrap();

            let context = PluginTraceContext::from_pyany(&dict.into_any()).unwrap();
            assert_eq!(
                context.traceparent.as_deref(),
                Some("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
            );
            assert_eq!(context.parent_span_id.as_deref(), Some("bbbbbbbbbbbbbbbb"));
        });
    }

    #[test]
    fn trace_context_rejects_non_dict_values() {
        with_python(|py| {
            let value = 123_i64.into_pyobject(py).unwrap();
            let err = PluginTraceContext::from_pyany(&value.into_any()).unwrap_err();
            assert!(err.is_instance_of::<PyValueError>(py));
        });
    }

    #[test]
    fn trace_context_optional_none_defaults() {
        with_python(|py| {
            let none_value = py.None().into_bound(py);
            let context = PluginTraceContext::from_optional_pyany(Some(&none_value)).unwrap();
            assert_eq!(context, PluginTraceContext::default());
        });
    }

    #[test]
    fn otlp_export_enabled_defaults_to_true() {
        with_isolated_env(&["OTEL_TRACES_EXPORTER"], || {
            assert!(otlp_export_enabled());
        });
    }

    #[test]
    fn otlp_export_enabled_rejects_non_otlp_exporters() {
        with_isolated_env(&["OTEL_TRACES_EXPORTER"], || {
            unsafe {
                std::env::set_var("OTEL_TRACES_EXPORTER", "none");
            }
            assert!(!otlp_export_enabled());
            unsafe {
                std::env::set_var("OTEL_TRACES_EXPORTER", "console");
            }
            assert!(!otlp_export_enabled());
        });
    }

    #[test]
    fn otlp_endpoint_falls_back_to_langfuse_endpoint() {
        with_isolated_env(
            &[
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "LANGFUSE_OTEL_ENDPOINT",
            ],
            || {
                unsafe {
                    std::env::set_var(
                        "LANGFUSE_OTEL_ENDPOINT",
                        "https://cloud.langfuse.com/api/public/otel",
                    );
                }
                assert_eq!(
                    otlp_endpoint().as_deref(),
                    Some("https://cloud.langfuse.com/api/public/otel")
                );
            },
        );
    }

    #[test]
    fn otlp_headers_adds_langfuse_basic_auth_when_missing() {
        with_isolated_env(
            &[
                "LANGFUSE_OTEL_ENDPOINT",
                "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_SECRET_KEY",
                "OTEL_EXPORTER_OTLP_HEADERS",
            ],
            || {
                unsafe {
                    std::env::set_var(
                        "LANGFUSE_OTEL_ENDPOINT",
                        "https://cloud.langfuse.com/api/public/otel",
                    );
                    std::env::set_var("LANGFUSE_PUBLIC_KEY", "pk-test");
                    std::env::set_var("LANGFUSE_SECRET_KEY", "sk-test");
                    std::env::remove_var("OTEL_EXPORTER_OTLP_HEADERS");
                }
                let headers = otlp_headers();
                assert_eq!(
                    headers.get("Authorization").map(String::as_str),
                    Some("Basic cGstdGVzdDpzay10ZXN0")
                );
            },
        );
    }

    #[test]
    fn resolve_langfuse_basic_auth_prefers_explicit_auth() {
        with_isolated_env(
            &[
                "LANGFUSE_OTEL_AUTH",
                "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_SECRET_KEY",
            ],
            || {
                unsafe {
                    std::env::set_var("LANGFUSE_OTEL_AUTH", "ZXhwbGljaXQ=");
                    std::env::set_var("LANGFUSE_PUBLIC_KEY", "pk-test");
                    std::env::set_var("LANGFUSE_SECRET_KEY", "sk-test");
                }
                assert_eq!(
                    resolve_langfuse_basic_auth().as_deref(),
                    Some("ZXhwbGljaXQ=")
                );
            },
        );
    }

    #[test]
    fn langfuse_endpoint_detection_requires_ingestion_path() {
        assert!(is_langfuse_endpoint(Some(
            "https://cloud.langfuse.com/api/public/otel"
        )));
        assert!(!is_langfuse_endpoint(Some(
            "https://evil.example/proxy/langfuse"
        )));
    }

    #[test]
    fn langfuse_config_requires_authorization() {
        with_isolated_env(
            &[
                "LANGFUSE_OTEL_ENDPOINT",
                "OTEL_EXPORTER_OTLP_HEADERS",
                "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_SECRET_KEY",
                "LANGFUSE_OTEL_AUTH",
            ],
            || {
                unsafe {
                    std::env::set_var(
                        "LANGFUSE_OTEL_ENDPOINT",
                        "https://cloud.langfuse.com/api/public/otel",
                    );
                    std::env::remove_var("OTEL_EXPORTER_OTLP_HEADERS");
                    std::env::remove_var("LANGFUSE_PUBLIC_KEY");
                    std::env::remove_var("LANGFUSE_SECRET_KEY");
                    std::env::remove_var("LANGFUSE_OTEL_AUTH");
                }
                assert!(!langfuse_config_valid(
                    "https://cloud.langfuse.com/api/public/otel"
                ));
            },
        );
    }

    #[test]
    fn langfuse_config_requires_valid_basic_authorization() {
        with_isolated_env(
            &["LANGFUSE_OTEL_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"],
            || {
                unsafe {
                    std::env::set_var(
                        "LANGFUSE_OTEL_ENDPOINT",
                        "https://cloud.langfuse.com/api/public/otel",
                    );
                    std::env::set_var("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer token");
                }
                assert!(!langfuse_config_valid(
                    "https://cloud.langfuse.com/api/public/otel"
                ));
            },
        );
    }
}
