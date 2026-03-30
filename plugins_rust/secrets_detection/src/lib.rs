mod config;
mod patterns;
mod scanner;

use std::collections::HashMap;
use std::fmt;
use std::str::FromStr;
use std::sync::OnceLock;
use std::time::Duration;

use log::{LevelFilter, debug, error, info, warn};
use opentelemetry::global;
use opentelemetry::trace::{Span, SpanContext, SpanId, TraceContextExt, TraceFlags, TraceId, TraceState, Tracer};
use opentelemetry::{Context, KeyValue};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::{
    Resource,
    trace::{RandomIdGenerator, Sampler, SdkTracerProvider},
};
use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString};
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;

pub use config::SecretsDetectionConfig;
pub use patterns::PATTERNS;
pub use scanner::{detect_and_redact, scan_container};

static TRACER_PROVIDER: OnceLock<Option<SdkTracerProvider>> = OnceLock::new();
static TOKIO_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

fn otel_resource() -> Resource {
    Resource::builder()
        .with_attributes([
            KeyValue::new("service.name", "secrets-detection-rust"),
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
        ])
        .build()
}

fn tokio_runtime() -> &'static tokio::runtime::Runtime {
    TOKIO_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("failed to build Tokio runtime for secrets_detection_rust")
    })
}

fn init_tracing() -> bool {
    if std::env::var("OTEL_ENABLE_OBSERVABILITY")
        .unwrap_or_else(|_| "false".to_string())
        .to_lowercase()
        != "true"
    {
        return false;
    }

    if let Some(provider) = TRACER_PROVIDER.get() {
        return provider.is_some();
    }

    let Some(endpoint) = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .ok()
        .filter(|value| !value.is_empty())
    else {
        warn!("Rust secrets detection tracing disabled: OTEL_EXPORTER_OTLP_ENDPOINT is not set");
        let _ = TRACER_PROVIDER.set(None);
        return false;
    };

    let exporter = match opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .with_timeout(Duration::from_secs(2))
        .build()
    {
        Ok(exporter) => exporter,
        Err(err) => {
            warn!("Failed to build Rust OTLP exporter for secrets detection: {}", err);
            let _ = TRACER_PROVIDER.set(None);
            return false;
        }
    };

    let provider = SdkTracerProvider::builder()
        .with_sampler(Sampler::ParentBased(Box::new(Sampler::AlwaysOn)))
        .with_id_generator(RandomIdGenerator::default())
        .with_resource(otel_resource())
        .with_simple_exporter(exporter)
        .build();
    global::set_tracer_provider(provider.clone());
    info!("Initialized OpenTelemetry exporter for secrets_detection_rust");
    let _ = TRACER_PROVIDER.set(Some(provider));
    true
}

fn parse_trace_context_headers(traceparent: Option<&str>, tracestate: Option<&str>) -> Option<Context> {
    let traceparent = traceparent?.trim();
    let mut parts = traceparent.split('-');
    let version = parts.next()?;
    let trace_id = parts.next()?;
    let parent_id = parts.next()?;
    let flags = parts.next()?;

    if parts.next().is_some() || version != "00" {
        return None;
    }

    let trace_id = TraceId::from_hex(trace_id).ok()?;
    let span_id = SpanId::from_hex(parent_id).ok()?;
    if trace_id == TraceId::INVALID || span_id == SpanId::INVALID {
        return None;
    }

    let raw_flags = u8::from_str_radix(flags, 16).ok()?;
    let trace_flags = if raw_flags & TraceFlags::SAMPLED.to_u8() != 0 {
        TraceFlags::SAMPLED
    } else {
        TraceFlags::default()
    };

    let trace_state = tracestate
        .filter(|value| !value.trim().is_empty())
        .map(TraceState::from_str)
        .transpose()
        .ok()?
        .unwrap_or_default();

    Some(Context::new().with_remote_span_context(SpanContext::new(
        trace_id,
        span_id,
        trace_flags,
        true,
        trace_state,
    )))
}

fn extract_parent_context(trace_context: Option<&Bound<'_, PyDict>>) -> Option<Context> {
    let trace_context = trace_context?;
    let traceparent = trace_context
        .get_item("traceparent")
        .ok()
        .flatten()
        .and_then(|value| value.extract::<String>().ok());
    let tracestate = trace_context
        .get_item("tracestate")
        .ok()
        .flatten()
        .and_then(|value| value.extract::<String>().ok());
    parse_trace_context_headers(traceparent.as_deref(), tracestate.as_deref())
}

/// Scan Python container for secrets using optimized type dispatch
///
#[gen_stub_pyfunction]
#[pyfunction]
fn py_scan_container<'py>(
    py: Python<'py>,
    container: Bound<'py, PyAny>,
    config: Bound<'py, PyAny>,
    trace_context: Option<Bound<'py, PyDict>>,
) -> PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> {
    let runtime_guard = tokio_runtime().enter();
    let tracing_active = init_tracing();
    let container_kind = describe_python_type(&container);
    debug!(
        "Starting Rust secrets scan for container_type={} at top level",
        container_kind
    );
    let parent_context = if tracing_active {
        extract_parent_context(trace_context.as_ref())
    } else {
        None
    };
    let mut otel_span = if tracing_active {
        let tracer = global::tracer("secrets-detection-rust");
        let mut span = if let Some(parent_context) = parent_context.as_ref() {
            tracer.start_with_context("secrets_detection.scan", parent_context)
        } else {
            tracer.start("secrets_detection.scan")
        };
        span.set_attribute(KeyValue::new("secrets.container_type", container_kind.to_string()));
        span.set_attribute(KeyValue::new("secrets.parent_context", parent_context.is_some()));
        Some(span)
    } else {
        None
    };

    let result: PyResult<(usize, Bound<'py, PyAny>, Bound<'py, PyList>)> = (|| {
        let cfg = SecretsDetectionConfig::try_from(&config)?;
        if let Some(span) = otel_span.as_mut() {
            span.set_attribute(KeyValue::new("secrets.redact", cfg.redact));
        }

        let (count, redacted, findings) = if container.is_instance_of::<PyString>() {
            let text = container.extract::<String>()?;
            let (fs, redacted_str) = detect_and_redact(&text, &cfg);

            let findings_list = PyList::empty(py);
            for finding in &fs {
                let finding_dict = PyDict::new(py);
                finding_dict.set_item("type", &finding.pii_type)?;
                finding_dict.set_item("match", &finding.preview)?;
                findings_list.append(finding_dict)?;
            }

            (
                fs.len(),
                PyString::new(py, &redacted_str).into_any(),
                findings_list,
            )
        } else if container.is_instance_of::<PyDict>() || container.is_instance_of::<PyList>() {
            scan_container(py, &container, &cfg)?
        } else {
            let findings = PyList::empty(py);
            (0, container.clone(), findings)
        };

        debug!(
            "Rust secrets scan finished for container_type={} with findings_count={}",
            container_kind, count
        );
        if let Some(span) = otel_span.as_mut() {
            span.set_attribute(KeyValue::new("secrets.findings_count", count as i64));
        }
        Ok((count, redacted, findings))
    })();

    if let Err(err) = &result {
        if let Some(span) = otel_span.as_mut() {
            span.set_attribute(KeyValue::new("error", true));
            span.set_attribute(KeyValue::new("error.message", err.to_string()));
        }
        error!(
            "Rust secrets scan failed for container_type={}: {}",
            container_kind, err
        );
    }

    if let Some(span) = otel_span.as_mut() {
        span.end();
    }
    drop(runtime_guard);

    result
}

#[pymodule]
fn secrets_detection_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    init_python_logging(m.py())?;
    m.add_function(wrap_pyfunction!(py_scan_container, m)?)?;
    info!("secrets_detection_rust module initialized");
    Ok(())
}

// Define stub info gatherer for generating Python type stubs
define_stub_info_gatherer!(stub_info);

/// Helper function to extract and convert Python attributes with custom error type
fn extract_attr<'py, T>(
    obj: &Bound<'py, PyAny>,
    attr_name: &str,
    expected_type: &str,
) -> PyResult<T>
where
    T: for<'a> FromPyObject<'a, 'a>,
{
    obj.getattr(attr_name)
        .map_err(|_| -> PyErr {
            error!("Missing required config attribute '{}'", attr_name);
            AttributeError::Missing {
                attr_name: attr_name.to_string(),
            }
            .into()
        })
        .and_then(|attr| {
            attr.extract().map_err(|_| -> PyErr {
                error!(
                    "Invalid type for config attribute '{}'; expected {}",
                    attr_name, expected_type
                );
                AttributeError::InvalidType {
                    attr_name: attr_name.to_string(),
                    expected_type: expected_type.to_string(),
                }
                .into()
            })
        })
}

/// TryFrom implementation for extracting SecretsDetectionConfig from Python objects
impl<'py> TryFrom<&Bound<'py, PyAny>> for SecretsDetectionConfig {
    type Error = PyErr;

    fn try_from(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        let enabled: HashMap<String, bool> = extract_attr(obj, "enabled", "Dict[str, bool]")?;
        let redact = extract_attr(obj, "redact", "bool")?;
        let redaction_text = extract_attr(obj, "redaction_text", "str")?;
        let block_on_detection = extract_attr(obj, "block_on_detection", "bool")?;
        let min_findings_to_block = extract_attr(obj, "min_findings_to_block", "int")?;

        debug!(
            "Loaded Rust secrets detection config: enabled_patterns={}, redact={}, block_on_detection={}, min_findings_to_block={}",
            enabled.len(),
            redact,
            block_on_detection,
            min_findings_to_block
        );

        Ok(SecretsDetectionConfig {
            enabled,
            redact,
            redaction_text,
            block_on_detection,
            min_findings_to_block,
        })
    }
}

fn init_python_logging(py: Python<'_>) -> PyResult<()> {
    let logger = pyo3_log::Logger::new(py, pyo3_log::Caching::Nothing)?
        .filter(LevelFilter::Trace)
        .filter_target("pyo3".to_string(), LevelFilter::Info);

    match logger.install() {
        Ok(_handle) => {
            info!("Initialized PyO3 log bridge for secrets_detection_rust");
            Ok(())
        }
        Err(err) => {
            warn!(
                "PyO3 log bridge for secrets_detection_rust already initialized or unavailable: {}",
                err
            );
            Ok(())
        }
    }
}

fn describe_python_type(container: &Bound<'_, PyAny>) -> &'static str {
    if container.is_instance_of::<PyString>() {
        "str"
    } else if container.is_instance_of::<PyDict>() {
        "dict"
    } else if container.is_instance_of::<PyList>() {
        "list"
    } else {
        "other"
    }
}

/// Custom error type for attribute extraction
#[derive(Debug)]
enum AttributeError {
    Missing {
        attr_name: String,
    },
    InvalidType {
        attr_name: String,
        expected_type: String,
    },
}

impl fmt::Display for AttributeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AttributeError::Missing { attr_name } => {
                write!(f, "Missing required attribute '{}'", attr_name)
            }
            AttributeError::InvalidType {
                attr_name,
                expected_type,
            } => {
                write!(
                    f,
                    "Invalid type for '{}', expected {}",
                    attr_name, expected_type
                )
            }
        }
    }
}

impl std::error::Error for AttributeError {}

impl From<AttributeError> for PyErr {
    fn from(err: AttributeError) -> PyErr {
        PyAttributeError::new_err(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry::trace::{SpanId, TraceFlags, TraceId};

    #[test]
    fn test_attribute_error_missing_display() {
        let err = AttributeError::Missing {
            attr_name: "test_attr".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Missing required attribute 'test_attr'");
    }

    #[test]
    fn test_attribute_error_invalid_type_display() {
        let err = AttributeError::InvalidType {
            attr_name: "test_attr".to_string(),
            expected_type: "str".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Invalid type for 'test_attr', expected str");
    }

    #[test]
    fn test_attribute_error_missing_debug() {
        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        let debug = format!("{:?}", err);
        assert!(debug.contains("Missing"));
        assert!(debug.contains("test"));
    }

    #[test]
    fn test_attribute_error_invalid_type_debug() {
        let err = AttributeError::InvalidType {
            attr_name: "field".to_string(),
            expected_type: "bool".to_string(),
        };
        let debug = format!("{:?}", err);
        assert!(debug.contains("InvalidType"));
        assert!(debug.contains("field"));
        assert!(debug.contains("bool"));
    }

    #[test]
    fn test_attribute_error_is_error_trait() {
        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        // Verify it implements std::error::Error
        let _: &dyn std::error::Error = &err;
    }

    #[test]
    fn test_attribute_error_display_with_special_chars() {
        let err = AttributeError::Missing {
            attr_name: "test_attr_123".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(display, "Missing required attribute 'test_attr_123'");
    }

    #[test]
    fn test_attribute_error_display_with_complex_type() {
        let err = AttributeError::InvalidType {
            attr_name: "config".to_string(),
            expected_type: "Dict[str, bool]".to_string(),
        };
        let display = format!("{}", err);
        assert_eq!(
            display,
            "Invalid type for 'config', expected Dict[str, bool]"
        );
    }

    #[test]
    fn test_attribute_error_conversion_exists() {
        fn _assert_conversion<T: Into<PyErr>>(_: T) {}

        let err = AttributeError::Missing {
            attr_name: "test".to_string(),
        };
        _assert_conversion(err);
    }

    #[test]
    fn test_parse_trace_context_headers_extracts_remote_parent() {
        let parent = parse_trace_context_headers(
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            Some("vendor=value"),
        )
        .expect("expected valid remote parent");

        let span = parent.span();
        let span_context = span.span_context();
        assert!(span_context.is_valid());
        assert!(span_context.is_remote());
        assert_eq!(
            span_context.trace_id(),
            TraceId::from_hex("4bf92f3577b34da6a3ce929d0e0e4736").expect("valid trace id") // pragma: allowlist secret
        );
        assert_eq!(
            span_context.span_id(),
            SpanId::from_hex("00f067aa0ba902b7").expect("valid span id")
        );
        assert_eq!(span_context.trace_flags(), TraceFlags::SAMPLED);
        assert_eq!(span_context.trace_state().header(), "vendor=value");
    }

    #[test]
    fn test_parse_trace_context_headers_rejects_invalid_parent() {
        assert!(parse_trace_context_headers(Some("00-invalid-parent-01"), None).is_none());
    }
}
