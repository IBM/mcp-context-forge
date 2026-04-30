# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Vendor-agnostic OpenTelemetry instrumentation for ContextForge.
Supports any OTLP-compatible backend (Jaeger, Zipkin, Tempo, Phoenix, etc.).
"""

# Standard
import base64
from contextlib import nullcontext
from importlib import import_module as _im
import logging
import os
from typing import Any, Callable, cast, Dict, Mapping, Optional
from urllib.parse import urlparse

# Third-Party - Try to import OpenTelemetry core components - make them truly optional
OTEL_AVAILABLE = False
try:
    # Third-Party
    from opentelemetry import trace
    from opentelemetry.propagate import extract as otel_extract
    from opentelemetry.propagate import inject as otel_inject
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from opentelemetry.trace import SpanKind, Status, StatusCode

    try:
        # Third-Party
        from opentelemetry import baggage as otel_baggage
    except ImportError:
        otel_baggage = None

    OTEL_AVAILABLE = True
except ImportError:
    # OpenTelemetry not installed - set to None for graceful degradation
    otel_baggage = None
    trace = None
    otel_extract = None
    otel_inject = None

    class _SpanKindShim:
        """Minimal SpanKind shim used when OpenTelemetry isn't installed."""

        SERVER = "server"

    # Provide a lightweight shim so tests can patch Resource.create
    class _ResourceShim:
        """Minimal Resource shim used when OpenTelemetry SDK isn't installed.

        Exposes a static ``create`` method that simply returns the provided
        attributes mapping, enabling tests to patch and inspect the inputs
        without requiring the real OpenTelemetry classes.
        """

        @staticmethod
        def create(attrs: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
            """Return attributes unchanged to mimic ``Resource.create``.

            Args:
                attrs: Resource attribute dictionary.

            Returns:
                Dict[str, Any]: The same mapping passed in.
            """
            return attrs

    Resource = cast(Any, _ResourceShim)
    TracerProvider = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    SimpleSpanProcessor = None
    SpanKind = cast(Any, _SpanKindShim)
    Status = None
    StatusCode = None

    # Provide minimal module shims so tests can patch ConsoleSpanExporter path
    try:
        # Standard
        import sys
        import types

        if ("pytest" in sys.modules) or (os.getenv("MCP_TESTING") == "1"):
            otel_root = types.ModuleType("opentelemetry")
            otel_sdk = types.ModuleType("opentelemetry.sdk")
            otel_trace = types.ModuleType("opentelemetry.sdk.trace")
            otel_export = types.ModuleType("opentelemetry.sdk.trace.export")

            class _ConsoleSpanExporterStub:  # pragma: no cover - test patch replaces this
                """Lightweight stub for ConsoleSpanExporter used in tests.

                Provides a placeholder class so unit tests can patch
                `opentelemetry.sdk.trace.export.ConsoleSpanExporter` even when
                the OpenTelemetry SDK is not installed in the environment.
                """

            setattr(otel_export, "ConsoleSpanExporter", _ConsoleSpanExporterStub)
            setattr(otel_trace, "export", otel_export)
            setattr(otel_sdk, "trace", otel_trace)
            setattr(otel_root, "sdk", otel_sdk)

            # Only register the exact chain needed by tests
            sys.modules.setdefault("opentelemetry", otel_root)
            sys.modules.setdefault("opentelemetry.sdk", otel_sdk)
            sys.modules.setdefault("opentelemetry.sdk.trace", otel_trace)
            sys.modules.setdefault("opentelemetry.sdk.trace.export", otel_export)
    except Exception as exc:  # nosec B110 - best-effort optional shim
        # Shimming is a non-critical, best-effort step for tests; log and continue.
        logging.getLogger(__name__).debug("Skipping OpenTelemetry shim setup: %s", exc)

# First-Party
from mcpgateway import __version__  # noqa: E402  # pylint: disable=wrong-import-position
from mcpgateway.config import get_settings  # noqa: E402  # pylint: disable=wrong-import-position
from mcpgateway.utils.correlation_id import get_correlation_id  # noqa: E402  # pylint: disable=wrong-import-position
from mcpgateway.utils.log_sanitizer import sanitize_for_log  # noqa: E402  # pylint: disable=wrong-import-position
from mcpgateway.utils.trace_context import (  # noqa: E402  # pylint: disable=wrong-import-position
    get_trace_auth_method,
    get_trace_session_id,
    get_trace_team_name,
    get_trace_team_scope,
    get_trace_user_email,
    get_trace_user_is_admin,
    primary_team_from_scope,
)
from mcpgateway.utils.trace_redaction import sanitize_trace_attribute_value, sanitize_trace_text  # noqa: E402  # pylint: disable=wrong-import-position

# Try to import optional exporters
try:
    OTLP_SPAN_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.grpc.trace_exporter"), "OTLPSpanExporter")
except Exception:
    try:
        OTLP_SPAN_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.http.trace_exporter"), "OTLPSpanExporter")
    except Exception:
        OTLP_SPAN_EXPORTER = None

try:
    JAEGER_EXPORTER = getattr(_im("opentelemetry.exporter.jaeger.thrift"), "JaegerExporter")
except Exception:
    JAEGER_EXPORTER = None

try:
    ZIPKIN_EXPORTER = getattr(_im("opentelemetry.exporter.zipkin.json"), "ZipkinExporter")
except Exception:
    ZIPKIN_EXPORTER = None

try:
    HTTP_EXPORTER = getattr(_im("opentelemetry.exporter.otlp.proto.http.trace_exporter"), "OTLPSpanExporter")
except Exception:
    HTTP_EXPORTER = None

logger = logging.getLogger(__name__)

_LANGFUSE_OTEL_PATH_FRAGMENT = "/api/public/otel"
_MAX_SPAN_EXCEPTION_MESSAGE_LENGTH = 1024
_IDENTITY_ATTRIBUTE_KEYS = frozenset({"user.email", "user.is_admin", "team.scope", "team.name", "langfuse.user.id"})


# Global tracer instance - using UPPER_CASE for module-level constant
# pylint: disable=invalid-name
_TRACER = None


def _sanitize_span_exception_message(exc_val: Optional[BaseException]) -> str:
    """Return a sanitized, bounded exception message for span attributes.

    Args:
        exc_val: Exception instance captured by the span lifecycle.

    Returns:
        Sanitized exception text safe to attach to OTEL and Langfuse attributes.
    """
    if exc_val is None:
        return ""

    sanitized = sanitize_trace_text(str(exc_val))
    sanitized = sanitize_for_log(sanitized).strip()
    if not sanitized:
        sanitized = exc_val.__class__.__name__

    if len(sanitized) <= _MAX_SPAN_EXCEPTION_MESSAGE_LENGTH:
        return sanitized

    truncated_length = _MAX_SPAN_EXCEPTION_MESSAGE_LENGTH - 3
    return f"{sanitized[:truncated_length]}..."


def _get_deployment_environment() -> str:
    """Return the current deployment environment label.

    Returns:
        Deployment environment label derived from configuration.
    """
    return get_settings().deployment_env


def _is_langfuse_otlp_endpoint(endpoint: Optional[str]) -> bool:
    """Return whether the OTLP endpoint points at a Langfuse ingestion path.

    Args:
        endpoint: OTLP endpoint URL to inspect.

    Returns:
        ``True`` when the endpoint path matches Langfuse's public OTLP ingestion path.
    """
    if not endpoint:
        return False

    try:
        return _LANGFUSE_OTEL_PATH_FRAGMENT in urlparse(endpoint).path
    except Exception:
        return _LANGFUSE_OTEL_PATH_FRAGMENT in endpoint


def _resolve_langfuse_basic_auth() -> str:
    """Resolve Langfuse OTLP basic auth from explicit auth or project keys.

    Returns:
        Base64-encoded Langfuse basic-auth credential string, or an empty string when Langfuse auth is not configured.
    """
    cfg = get_settings()
    explicit_auth = cfg.langfuse_otel_auth.get_secret_value().strip() if cfg.langfuse_otel_auth else ""
    if explicit_auth:
        return explicit_auth

    public_key = cfg.langfuse_public_key.get_secret_value().strip() if cfg.langfuse_public_key else ""
    secret_key = cfg.langfuse_secret_key.get_secret_value().strip() if cfg.langfuse_secret_key else ""
    if not public_key or not secret_key:
        return ""

    return base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")


def _resolve_otlp_endpoint() -> Optional[str]:
    """Resolve the OTLP endpoint from generic or Langfuse-specific configuration.

    Returns:
        Configured OTLP endpoint, preferring the Langfuse-specific override when present.
    """
    cfg = get_settings()
    return cfg.langfuse_otel_endpoint or cfg.otel_exporter_otlp_endpoint


def _parse_otlp_headers(headers: Optional[str]) -> Dict[str, str]:
    """Parse OTLP headers from a comma-separated key=value string.

    Args:
        headers: Raw header string from configuration.

    Returns:
        Parsed OTLP headers mapping.
    """
    parsed: Dict[str, str] = {}
    if not headers:
        return parsed

    for header in headers.split(","):
        if "=" not in header:
            continue
        key, value = header.split("=", 1)
        key = key.strip()
        if key:
            parsed[key] = value.strip()
    return parsed


def _get_header_case_insensitive(headers: Dict[str, str], name: str) -> Optional[str]:
    """Return a header value using case-insensitive name matching.

    Args:
        headers: Header mapping to inspect.
        name: Header name to resolve.

    Returns:
        Matching header value, or ``None`` when not present.
    """
    normalized_name = name.lower()
    for key, value in headers.items():
        if key.lower() == normalized_name:
            return value
    return None


def _set_header_case_insensitive(headers: Dict[str, str], name: str, value: str) -> None:
    """Set a header value while preserving an existing key's original casing when present.

    Args:
        headers: Header mapping to mutate.
        name: Header name to set.
        value: Header value to store.
    """
    normalized_name = name.lower()
    for key in list(headers.keys()):
        if key.lower() == normalized_name:
            headers[key] = value
            return
    headers[name] = value


def _resolve_otlp_headers(endpoint: Optional[str]) -> Dict[str, str]:
    """Resolve OTLP headers, deriving Langfuse basic auth when possible.

    Args:
        endpoint: Resolved OTLP endpoint URL.

    Returns:
        OTLP header mapping suitable for exporter configuration.
    """
    cfg = get_settings()
    headers = _parse_otlp_headers(cfg.otel_exporter_otlp_headers)

    if not _is_langfuse_otlp_endpoint(endpoint):
        return headers

    basic_auth = _resolve_langfuse_basic_auth()
    if basic_auth and not _get_header_case_insensitive(headers, "Authorization"):
        _set_header_case_insensitive(headers, "Authorization", f"Basic {basic_auth}")

    return headers


def _validate_langfuse_configuration(endpoint: Optional[str], headers: Dict[str, str]) -> None:
    """Fail closed when Langfuse OTLP is configured without usable credentials.

    Args:
        endpoint: OTLP endpoint URL configured for export.
        headers: Authorization header value configured for the OTLP exporter.

    Raises:
        RuntimeError: If a Langfuse endpoint is configured without credentials.
    """
    if not _is_langfuse_otlp_endpoint(endpoint):
        return

    authorization = _get_header_case_insensitive(headers, "Authorization")
    if authorization:
        try:
            scheme, encoded = authorization.strip().split(None, 1)
            decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
            public_key, secret_key = decoded.split(":", 1)
            if scheme.lower() == "basic" and public_key and secret_key:
                return
        except (ValueError, UnicodeDecodeError):
            pass

    message = (
        "Langfuse OTLP endpoint configured without valid Basic Authorization credentials. " + "Set OTEL_EXPORTER_OTLP_HEADERS, LANGFUSE_OTEL_AUTH, " + "or LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
    )
    raise RuntimeError(message)


def _should_emit_langfuse_attributes() -> bool:
    """Return whether Langfuse-specific span attributes should be emitted.

    Returns:
        ``True`` when Langfuse-specific span attributes should be attached.
    """
    cfg = get_settings()
    if cfg.otel_emit_langfuse_attributes is not None:
        return cfg.otel_emit_langfuse_attributes
    return _is_langfuse_otlp_endpoint(_resolve_otlp_endpoint())


def _should_capture_identity_attributes() -> bool:
    """Return whether user/team identity attributes should be emitted on spans.

    Returns:
        ``True`` when user/team identity metadata should be attached to spans.
    """
    cfg = get_settings()
    if cfg.otel_capture_identity_attributes is not None:
        return cfg.otel_capture_identity_attributes
    return _should_emit_langfuse_attributes()


def _should_emit_span_attribute(attribute_name: str) -> bool:
    """Return whether a span attribute should be emitted under current policy.

    Args:
        attribute_name: Span attribute key.

    Returns:
        ``True`` when the attribute passes the current export policy.
    """
    if attribute_name.startswith("langfuse.") and not _should_emit_langfuse_attributes():
        return False
    if attribute_name in _IDENTITY_ATTRIBUTE_KEYS and not _should_capture_identity_attributes():
        return False
    return True


def set_span_attribute(span: Any, attribute_name: str, value: Any) -> None:
    """Set a span attribute after applying export and sanitization policy.

    Args:
        span: Active span object.
        attribute_name: Span attribute key.
        value: Attribute value to set.
    """
    if not span or value is None:
        return
    if not _should_emit_span_attribute(attribute_name):
        return
    span.set_attribute(attribute_name, sanitize_trace_attribute_value(attribute_name, value))


def _set_pre_sanitized_span_attribute(span: Any, attribute_name: str, value: Any) -> None:
    """Set a span attribute that has already been sanitized and bounded.

    Args:
        span: Active span object.
        attribute_name: Span attribute key.
        value: Pre-sanitized attribute value to set.
    """
    if not span or value is None:
        return
    if not _should_emit_span_attribute(attribute_name):
        return
    span.set_attribute(attribute_name, value)


def _record_sanitized_exception_event(span: Any, exc_type: Optional[type], error_message: str) -> None:
    """Record a sanitized exception event on a span without exporting raw exception text.

    Args:
        span: Active span object.
        exc_type: Exception class associated with the failure.
        error_message: Sanitized exception message to attach to the event.
    """
    if not span or exc_type is None:
        return

    attrs = {
        "exception.type": exc_type.__name__,
        "exception.message": error_message,
        "exception.escaped": True,
    }

    if hasattr(span, "add_event"):
        span.add_event("exception", attributes=attrs)
        return

    if hasattr(span, "record_exception"):
        try:
            sanitized_exc = exc_type(error_message)
        except Exception:
            sanitized_exc = Exception(error_message)
        span.record_exception(sanitized_exc)


def set_span_error(
    span: Any,
    error: str | BaseException,
    *,
    exc_type: Optional[type] = None,
    record_exception: bool = False,
) -> None:
    """Mark a span as failed with a sanitized error message.

    Args:
        span: Active span object.
        error: Exception instance or message text describing the failure.
        exc_type: Optional explicit exception type for the failure.
        record_exception: Whether to add a sanitized exception event to the span.
    """
    if not span:
        return

    if isinstance(error, BaseException):
        error_message = _sanitize_span_exception_message(error)
        resolved_exc_type = exc_type or type(error)
    else:
        error_message = sanitize_for_log(sanitize_trace_text(str(error))).strip() or "Error"
        resolved_exc_type = exc_type

    if record_exception:
        _record_sanitized_exception_event(span, resolved_exc_type, error_message)

    if OTEL_AVAILABLE and Status and StatusCode:
        span.set_status(Status(StatusCode.ERROR, error_message))

    set_span_attribute(span, "error", True)
    if resolved_exc_type is not None:
        set_span_attribute(span, "error.type", resolved_exc_type.__name__)
    _set_pre_sanitized_span_attribute(span, "error.message", error_message)
    set_span_attribute(span, "langfuse.observation.level", "ERROR")
    _set_pre_sanitized_span_attribute(span, "langfuse.observation.status_message", error_message)


def _derive_langfuse_trace_name(name: str, attributes: Dict[str, Any]) -> str:
    """Derive a human-readable Langfuse trace name from span context.

    Args:
        name: Raw span name.
        attributes: Span attributes used to derive a more readable Langfuse trace label.

    Returns:
        Human-readable trace name suitable for Langfuse dashboards.
    """

    def _display_value(value: Any) -> Any:
        """Sanitize string display values before promoting them into a trace name.

        Args:
            value: Candidate trace-name fragment.

        Returns:
            Sanitized string values, or the original non-string value unchanged.
        """
        if isinstance(value, str):
            return sanitize_trace_text(value)
        return value

    if name == "tool.invoke" and attributes.get("tool.name"):
        return f"Tool: {_display_value(attributes['tool.name'])}"
    if name == "tool.list":
        return "Tools"
    if name == "prompt.render" and attributes.get("prompt.id"):
        return f"Prompt: {_display_value(attributes['prompt.id'])}"
    if name == "prompt.list":
        return "Prompts"
    if name == "resource.read" and attributes.get("resource.uri"):
        return f"Resource: {_display_value(attributes['resource.uri'])}"
    if name == "resource.list":
        return "Resources"
    if name == "resource_template.list":
        return "Resource Templates"
    if name == "root.list":
        return "Roots"
    if name in {"llm.proxy", "llm.chat"} and attributes.get("gen_ai.request.model"):
        prefix = "LLM Proxy" if name == "llm.proxy" else "LLM Chat"
        return f"{prefix}: {_display_value(attributes['gen_ai.request.model'])}"
    if name.startswith("a2a.") and attributes.get("a2a.agent.name"):
        return f"A2A: {_display_value(attributes['a2a.agent.name'])}"
    return name


def otel_tracing_enabled() -> bool:
    """Return whether OpenTelemetry tracing is active in this process.

    Returns:
        bool: ``True`` when a tracer has been initialised, otherwise ``False``.
    """

    return _TRACER is not None


def otel_context_active() -> bool:
    """Return whether the current async context carries an active OTEL span.

    Returns:
        bool: ``True`` when the current context has a valid OTEL span.
    """

    if not OTEL_AVAILABLE or trace is None:
        return False
    try:
        current_span = trace.get_current_span()
        if current_span is None:
            return False
        span_context = current_span.get_span_context()
        return bool(getattr(span_context, "is_valid", False))
    except Exception:
        return False


def inject_trace_context_headers(headers: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Return a header carrier populated with the active W3C trace context and baggage.

    Args:
        headers: Existing outbound headers to copy into the carrier before trace injection.

    Returns:
        Dict[str, str]: Header mapping including any injected trace context and baggage.
    """

    carrier = {str(key): str(value) for key, value in (headers or {}).items() if key and value}
    if not otel_context_active() or otel_inject is None:
        return carrier
    try:
        otel_inject(carrier=carrier)
    except Exception as exc:
        logger.debug("Failed to inject W3C trace context into outbound headers: %s", exc)

    # Inject baggage if propagation is enabled
    try:
        settings = get_settings()
        if settings.otel_baggage_enabled and settings.otel_baggage_propagate_to_external:
            if OTEL_AVAILABLE and otel_baggage:
                baggage_dict = otel_baggage.get_all()
                if baggage_dict:
                    # First-Party
                    from mcpgateway.baggage import format_w3c_baggage_header, sanitize_baggage_for_propagation

                    # Sanitize baggage before propagation
                    sanitized_baggage = sanitize_baggage_for_propagation(baggage_dict)
                    if sanitized_baggage:
                        baggage_header = format_w3c_baggage_header(sanitized_baggage)
                        carrier["baggage"] = baggage_header
                        logger.debug(f"Injected {len(sanitized_baggage)} baggage entries into outbound headers")
    except Exception as exc:
        logger.debug("Failed to inject baggage into outbound headers: %s", exc)

    return carrier


def _scope_headers_to_carrier(scope_headers: list[tuple[bytes, bytes]]) -> Dict[str, str]:
    """Convert ASGI scope headers to a text carrier for propagation/extraction.

    Args:
        scope_headers: Raw ASGI header tuples from the request scope.

    Returns:
        Dict[str, str]: Decoded lower-cased header carrier suitable for OTEL propagation.
    """

    carrier: Dict[str, str] = {}
    for key, value in scope_headers:
        try:
            decoded_key = key.decode("latin-1").lower()
            decoded_value = value.decode("latin-1")
        except (AttributeError, TypeError, UnicodeDecodeError):
            continue
        carrier[decoded_key] = decoded_value
    return carrier


def _should_trace_request_path(path: str) -> bool:
    """Return whether Phase 1 OTEL request tracing should instrument the path.

    Args:
        path: Incoming request path.

    Returns:
        bool: ``True`` when the path should be wrapped in a request span.
    """

    normalized = path.rstrip("/") or "/"
    if normalized in {"/rpc", "/mcp", "/mcp/sse", "/mcp/message", "/message", "/sse"}:
        return True
    if normalized.startswith("/servers/") and (normalized.endswith("/mcp") or normalized.endswith("/message") or normalized.endswith("/sse")):
        return True
    if normalized.startswith("/_internal/mcp/"):
        return True
    return False


class OpenTelemetryRequestMiddleware:
    """Raw ASGI middleware that creates request-root spans for gateway transport flows."""

    def __init__(self, app: Any, should_trace_request_path: Optional[Callable[[str], bool]] = None):
        """Initialize the middleware wrapper.

        Args:
            app: Wrapped ASGI application.
            should_trace_request_path: Optional predicate that decides whether a request path
                should be instrumented.
        """
        self.app = app
        self.should_trace_request_path = should_trace_request_path or _should_trace_request_path

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the wrapped ASGI app.

        This preserves access to app-specific attributes such as ``routes`` when
        the middleware is used as the top-level object passed to uvicorn.

        Args:
            name: Attribute name to resolve on the wrapped ASGI app.

        Returns:
            Any: The proxied attribute value from ``self.app``.
        """

        return getattr(self.app, name)

    async def __call__(self, scope: Mapping[str, Any], receive: Any, send: Any) -> None:
        """Handle an ASGI request and create a request-root span when tracing applies.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        Raises:
            Exception: Any exception raised by the wrapped ASGI application.
        """
        if scope.get("type") != "http" or _TRACER is None:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", "") or "")
        if not self.should_trace_request_path(path):
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET") or "GET").upper()
        scope_headers = list(scope.get("headers", []) or [])
        carrier = _scope_headers_to_carrier(scope_headers)

        parent_context = None
        if otel_extract is not None:
            try:
                parent_context = otel_extract(carrier=carrier)
            except Exception as exc:
                logger.debug("Failed to extract W3C trace context for %s %s: %s", method, path, exc)

        server = scope.get("server") or ("", None)
        client = scope.get("client") or ("", None)
        query_string = scope.get("query_string", b"") or b""
        if isinstance(query_string, bytes):
            query_text = query_string.decode("latin-1")
        else:
            query_text = str(query_string)

        # Sanitize query string to prevent leaking session_id and other sensitive parameters
        sanitized_query = sanitize_trace_text(query_text) if query_text else None

        span_name = f"{method} {path or '/'}"
        span_attributes: Dict[str, Any] = {
            "http.request.method": method,
            "http.route": path or "/",
            "url.path": path or "/",
            "url.query": sanitized_query,
            "network.protocol.version": scope.get("http_version"),
            "server.address": server[0] if len(server) > 0 else None,
            "server.port": server[1] if len(server) > 1 else None,
            "client.address": client[0] if len(client) > 0 else None,
            "client.port": client[1] if len(client) > 1 else None,
            "user_agent.original": carrier.get("user-agent"),
            "correlation_id": carrier.get("x-correlation-id"),
        }

        start_span_kwargs: Dict[str, Any] = {}
        if parent_context is not None:
            start_span_kwargs["context"] = parent_context
        if SpanKind is not None:
            start_span_kwargs["kind"] = SpanKind.SERVER

        status_code_holder: Dict[str, int] = {}

        async def _send_with_span_status(message: Mapping[str, Any]) -> None:
            """Send an ASGI message and update the span status from the HTTP response.

            If the message is an ``http.response.start`` event, the HTTP status code
            is extracted, stored, and applied to the active span. Status codes >= 500
            mark the span as an error; all others are marked as OK.

            Args:
                message: ASGI message dictionary from which the HTTP status code
                    may be retrieved.
            """
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 0) or 0)
                status_code_holder["status"] = status_code
                if span is not None and status_code:
                    set_span_attribute(span, "http.response.status_code", status_code)
                    if OTEL_AVAILABLE and Status and StatusCode:
                        if status_code >= 500:
                            span.set_status(Status(StatusCode.ERROR))
                        else:
                            span.set_status(Status(StatusCode.OK))
            await send(message)

        with _TRACER.start_as_current_span(span_name, **start_span_kwargs) as span:
            if span is not None:
                for key, value in span_attributes.items():
                    if value is not None:
                        set_span_attribute(span, key, value)

                # Inject baggage as span attributes so request-root spans retain
                # the same trace context dimensions carried on child spans.
                try:
                    if OTEL_AVAILABLE and otel_baggage:
                        baggage_dict = otel_baggage.get_all()
                        if baggage_dict:
                            for key, value in baggage_dict.items():
                                set_span_attribute(span, f"baggage.{key}", value)
                            logger.debug("Injected %d baggage entries into request span", len(baggage_dict))
                except Exception as exc:
                    logger.debug("Failed to inject baggage into request span: %s", exc)

            try:
                await self.app(scope, receive, _send_with_span_status)
                if span is not None and "status" not in status_code_holder and OTEL_AVAILABLE and Status and StatusCode:
                    span.set_status(Status(StatusCode.OK))
            except Exception as exc:
                if span is not None:
                    error_message = _sanitize_span_exception_message(exc)
                    set_span_error(span, exc, record_exception=True)
                    if OTEL_AVAILABLE and Status and StatusCode:
                        span.set_status(Status(StatusCode.ERROR, error_message))
                raise


def init_telemetry() -> Optional[Any]:
    """Initialize OpenTelemetry with configurable backend.

    Supports multiple backends via environment variables:
    - OTEL_TRACES_EXPORTER: Exporter type (otlp, jaeger, zipkin, console, none)
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (for otlp exporter)
    - OTEL_EXPORTER_JAEGER_ENDPOINT: Jaeger endpoint (for jaeger exporter)
    - OTEL_EXPORTER_ZIPKIN_ENDPOINT: Zipkin endpoint (for zipkin exporter)
    - OTEL_ENABLE_OBSERVABILITY: Set to 'true' to enable (disabled by default)

    Returns:
        The initialized tracer instance or None if disabled.
    """
    # pylint: disable=global-statement
    global _TRACER
    cfg = get_settings()

    # Check if observability is disabled (default: disabled)
    if not cfg.otel_enable_observability:
        logger.info("Observability disabled via OTEL_ENABLE_OBSERVABILITY=false")
        return None

    # If OpenTelemetry isn't installed, return early with graceful degradation
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not installed - telemetry disabled")
        logger.info("To enable telemetry, install: pip install mcp-contextforge-gateway[observability]")
        return None

    # Get exporter type from environment
    exporter_type = cfg.otel_traces_exporter.lower()

    # Handle 'none' exporter (tracing disabled)
    if exporter_type == "none":
        logger.info("Tracing disabled via OTEL_TRACES_EXPORTER=none")
        return None

    # Check if endpoint is configured for otlp
    if exporter_type == "otlp":
        endpoint = _resolve_otlp_endpoint()
        if not endpoint:
            logger.info("OTLP endpoint not configured, skipping telemetry init")
            return None
        _validate_langfuse_configuration(endpoint, _resolve_otlp_headers(endpoint))

    try:
        # Create resource attributes
        resource_attributes: Dict[str, Any] = {
            "service.name": cfg.otel_service_name,
            "service.version": __version__,
            "deployment.environment": _get_deployment_environment(),
        }

        # Add custom resource attributes from environment
        custom_attrs = cfg.otel_resource_attributes or ""
        if custom_attrs:
            for attr in custom_attrs.split(","):
                if "=" in attr:
                    key, value = attr.split("=", 1)
                    resource_attributes[key.strip()] = value.strip()

        # Narrow types for mypy/pyrefly
        # Create resource if available, else skip
        resource: Optional[Any]
        if Resource is not None and hasattr(Resource, "create"):
            resource = cast(Any, Resource).create(resource_attributes)
        else:
            resource = None

        # Set up tracer provider with optional sampling
        # Initialize tracer provider (with resource if available)
        if resource is not None:
            provider = cast(Any, TracerProvider)(resource=resource)
        else:
            provider = cast(Any, TracerProvider)()

        # Register provider if trace API is present
        if trace is not None and hasattr(trace, "set_tracer_provider"):
            cast(Any, trace).set_tracer_provider(provider)

        # Create a custom span processor to copy resource attributes to span attributes
        # This is needed because Arize requires arize.project.name as a span attribute
        class ResourceAttributeSpanProcessor:
            """Span processor that copies specific resource attributes to span attributes."""

            def __init__(self, attributes_to_copy=None):
                self.attributes_to_copy = attributes_to_copy or ["arize.project.name", "model_id"]
                logger.info(f"ResourceAttributeSpanProcessor will copy: {self.attributes_to_copy}")

            def on_start(self, span, _parent_context=None):
                """Copy specified resource attributes to span attributes when span starts.

                Args:
                    span: The span being started.
                    _parent_context: The parent context (unused, required by interface).
                """
                if not hasattr(span, "resource") or span.resource is None:
                    return

                # Get resource attributes
                resource_attributes = getattr(span.resource, "attributes", {})

                # Copy specified attributes from resource to span
                for attr in self.attributes_to_copy:
                    if attr in resource_attributes:
                        value = resource_attributes[attr]
                        span.set_attribute(attr, value)
                        logger.debug(f"Copied resource attribute to span: {attr}={value}")

            def on_end(self, span):
                """Handle span end event.

                Required by the SpanProcessor interface but not used.

                Args:
                    span: The span being ended.
                """
                pass  # pylint: disable=unnecessary-pass

        # Add the custom span processor to copy resource attributes to spans
        # This is needed for Arize which requires certain attributes as span attributes
        # Enable via OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=true (disabled by default)
        copy_resource_attrs = cfg.otel_copy_resource_attrs_to_spans
        if resource is not None and copy_resource_attrs:
            logger.info("Adding ResourceAttributeSpanProcessor to copy resource attributes to spans")
            provider.add_span_processor(ResourceAttributeSpanProcessor())

        # Configure the appropriate exporter based on type
        exporter: Optional[Any] = None

        if exporter_type == "otlp":
            endpoint = _resolve_otlp_endpoint()
            protocol = cfg.otel_exporter_otlp_protocol.lower()
            header_dict = _resolve_otlp_headers(endpoint)
            if _is_langfuse_otlp_endpoint(endpoint):
                protocol = "http"
            # Note: some versions of OTLP exporters may not accept 'insecure' kwarg; avoid passing it.
            # Use endpoint scheme or env to control TLS externally.

            if protocol == "grpc" and OTLP_SPAN_EXPORTER:
                exporter = cast(Any, OTLP_SPAN_EXPORTER)(endpoint=endpoint, headers=header_dict or None)
            elif HTTP_EXPORTER:
                # Use HTTP exporter as fallback
                ep = str(endpoint) if endpoint is not None else ""
                http_ep = (ep.replace(":4317", ":4318") + "/v1/traces") if ":4317" in ep else ep
                exporter = cast(Any, HTTP_EXPORTER)(endpoint=http_ep, headers=header_dict or None)
            else:
                logger.error("No OTLP exporter available")
                return None

        elif exporter_type == "jaeger":
            if JAEGER_EXPORTER:
                endpoint = cfg.otel_exporter_jaeger_endpoint or "http://localhost:14268/api/traces"
                exporter = JAEGER_EXPORTER(
                    collector_endpoint=endpoint,
                    username=cfg.otel_exporter_jaeger_user,
                    password=cfg.otel_exporter_jaeger_password.get_secret_value() if cfg.otel_exporter_jaeger_password else None,
                )
            else:
                logger.error("Jaeger exporter not available. Install with: pip install opentelemetry-exporter-jaeger")
                return None

        elif exporter_type == "zipkin":
            if ZIPKIN_EXPORTER:
                endpoint = cfg.otel_exporter_zipkin_endpoint or "http://localhost:9411/api/v2/spans"
                exporter = ZIPKIN_EXPORTER(endpoint=endpoint)
            else:
                logger.error("Zipkin exporter not available. Install with: pip install opentelemetry-exporter-zipkin")
                return None

        elif exporter_type == "console":
            # Console exporter for debugging
            exporter = cast(Any, ConsoleSpanExporter)()

        else:
            logger.warning(f"Unknown exporter type: {exporter_type}. Using console exporter.")
            exporter = cast(Any, ConsoleSpanExporter)()

        if exporter:
            # Add batch processor for better performance (except for console)
            if exporter_type == "console":
                span_processor = cast(Any, SimpleSpanProcessor)(exporter)
            else:
                span_processor = cast(Any, BatchSpanProcessor)(
                    exporter,
                    max_queue_size=cfg.otel_bsp_max_queue_size,
                    max_export_batch_size=cfg.otel_bsp_max_export_batch_size,
                    schedule_delay_millis=cfg.otel_bsp_schedule_delay,
                )
            provider.add_span_processor(span_processor)

        # Get tracer
        # Obtain a tracer if trace API available; otherwise create a no-op tracer
        if trace is not None and hasattr(trace, "get_tracer"):
            _TRACER = cast(Any, trace).get_tracer("mcp-gateway", __version__, schema_url="https://opentelemetry.io/schemas/1.11.0")
        else:

            class _NoopTracer:
                """No-op tracer used when OpenTelemetry API isn't available."""

                def start_as_current_span(self, _name: str):  # type: ignore[override]
                    """Return a no-op context manager for span creation.

                    Args:
                        _name: Span name (ignored in no-op implementation).

                    Returns:
                        contextlib.AbstractContextManager: A null context.
                    """
                    return nullcontext()

            _TRACER = _NoopTracer()

        logger.info(f"✅ OpenTelemetry initialized with {exporter_type} exporter")
        if exporter_type == "otlp":
            logger.info(f"   Endpoint: {_resolve_otlp_endpoint()}")
        elif exporter_type == "jaeger":
            logger.info(f"   Endpoint: {cfg.otel_exporter_jaeger_endpoint or 'default'}")
        elif exporter_type == "zipkin":
            logger.info(f"   Endpoint: {cfg.otel_exporter_zipkin_endpoint or 'default'}")

        return _TRACER

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return None


def trace_operation(operation_name: str, attributes: Optional[Dict[str, Any]] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Simple decorator to trace any operation.

    Args:
        operation_name: Name of the operation to trace (e.g., "tool.invoke").
        attributes: Optional dictionary of attributes to add to the span.

    Returns:
        Decorator function that wraps the target function with tracing.

    Usage:
        @trace_operation("tool.invoke", {"tool.name": "calculator"})
        async def invoke_tool():
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator that wraps the function with tracing.

        Args:
            func: The async function to wrap with tracing.

        Returns:
            The wrapped function with tracing capabilities.
        """

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Async wrapper that adds tracing to the decorated function.

            Args:
                *args: Positional arguments passed to the wrapped function.
                **kwargs: Keyword arguments passed to the wrapped function.

            Returns:
                The result of the wrapped function.

            Raises:
                Exception: Any exception raised by the wrapped function.
            """
            if not _TRACER:
                # No tracing configured, just run the function
                return await func(*args, **kwargs)

            # Create span for this operation
            with _TRACER.start_as_current_span(operation_name) as span:
                # Add attributes if provided
                if attributes:
                    for key, value in attributes.items():
                        set_span_attribute(span, key, value)

                try:
                    # Run the actual function
                    result = await func(*args, **kwargs)
                    set_span_attribute(span, "status", "success")
                    return result
                except Exception as e:
                    set_span_attribute(span, "status", "error")
                    set_span_error(span, e, record_exception=True)
                    raise

        return wrapper

    return decorator


def create_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Any:
    """
    Create a span for manual instrumentation.

    Args:
        name: Name of the span to create (e.g., "database.query").
        attributes: Optional dictionary of attributes to add to the span.

    Returns:
        Context manager that creates and manages the span lifecycle.

    Usage:
        with create_span("database.query", {"db.statement": "SELECT * FROM tools"}):
            # Your code here
            pass
    """
    if not _TRACER:
        # Return a no-op context manager if tracing is not configured or available
        return nullcontext()

    attributes = dict(attributes or {})

    # Auto-inject correlation ID into all spans for request tracing
    try:
        correlation_id = get_correlation_id()
        if correlation_id:
            attributes.setdefault("correlation_id", correlation_id)
            attributes.setdefault("request_id", correlation_id)
    except Exception as exc:
        # Correlation ID not available or error getting it, continue without it
        logger.debug("Failed to add correlation_id to span: %s", exc)

    try:
        user_email = get_trace_user_email()
        user_is_admin = get_trace_user_is_admin()
        team_scope = get_trace_team_scope()
        team_name = get_trace_team_name()
        auth_method = get_trace_auth_method()
        session_id = get_trace_session_id()
        environment = _get_deployment_environment()

        if _should_capture_identity_attributes():
            if user_email:
                attributes.setdefault("user.email", user_email)
            if user_email or user_is_admin:
                attributes.setdefault("user.is_admin", user_is_admin)
            if team_scope:
                attributes.setdefault("team.scope", team_scope)
            if team_name:
                attributes.setdefault("team.name", team_name)

        if auth_method:
            attributes.setdefault("auth.method", auth_method)

        if _should_emit_langfuse_attributes():
            if _should_capture_identity_attributes() and user_email:
                attributes.setdefault("langfuse.user.id", user_email)
            if session_id:
                attributes.setdefault("langfuse.session.id", session_id)
            attributes.setdefault("langfuse.environment", environment)

            tags: list[str] = []
            primary_team = primary_team_from_scope(team_scope)
            if _should_capture_identity_attributes() and primary_team:
                tags.append(f"team:{primary_team}")
            if auth_method:
                tags.append(f"auth:{auth_method}")
            if environment:
                tags.append(f"env:{environment}")
            if tags:
                attributes.setdefault("langfuse.trace.tags", tags)

            trace_name_attributes = {key: sanitize_trace_attribute_value(key, value) for key, value in attributes.items() if _should_emit_span_attribute(key)}
            attributes.setdefault("langfuse.trace.name", _derive_langfuse_trace_name(name, trace_name_attributes))
            attributes.setdefault("langfuse.observation.level", "DEFAULT")
    except Exception as exc:
        logger.debug("Failed to auto-inject trace context into span: %s", exc)

    # Auto-inject baggage as span attributes
    try:
        if OTEL_AVAILABLE and otel_baggage:
            baggage_dict = otel_baggage.get_all()
            if baggage_dict:
                for key, value in baggage_dict.items():
                    # Prefix baggage attributes to distinguish from direct attributes
                    attributes.setdefault(f"baggage.{key}", value)
                logger.debug(f"Injected {len(baggage_dict)} baggage entries as span attributes")
    except Exception:
        logger.warning("Failed to inject baggage into span attributes", exc_info=True)

    # Start span and return the context manager
    span_context = _TRACER.start_as_current_span(name)

    # If we have attributes and the span context is entered, set them
    if attributes:
        # We need to set attributes after entering the context
        # So we'll create a wrapper that sets attributes
        class SpanWithAttributes:
            """Context manager wrapper that adds attributes to a span.

            This class wraps an OpenTelemetry span context and adds attributes
            when entering the context. It also handles exception recording when
            exiting the context.
            """

            def __init__(self, span_context: Any, attrs: Dict[str, Any]):
                """Initialize the span wrapper.

                Args:
                    span_context: The OpenTelemetry span context to wrap.
                    attrs: Dictionary of attributes to add to the span.
                """
                self.span_context: Any = span_context
                self.attrs: Dict[str, Any] = attrs
                self.span: Any = None

            def __enter__(self) -> Any:
                """Enter the context and set span attributes.

                Returns:
                    The OpenTelemetry span with attributes set.
                """
                self.span = self.span_context.__enter__()
                if self.attrs and self.span:
                    for key, value in self.attrs.items():
                        if value is not None:  # Skip None values
                            set_span_attribute(self.span, key, value)
                return self.span

            def __exit__(self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Any) -> Any:
                """Exit the context and record any exceptions.

                Args:
                    exc_type: The exception type if an exception occurred.
                    exc_val: The exception value if an exception occurred.
                    exc_tb: The exception traceback if an exception occurred.

                Returns:
                    The result of the wrapped span context's __exit__ method.
                """
                # Record exception if one occurred
                if exc_type is not None and self.span:
                    set_span_error(self.span, exc_val or exc_type.__name__, exc_type=exc_type, record_exception=True)
                elif self.span:
                    if OTEL_AVAILABLE and Status and StatusCode:
                        self.span.set_status(Status(StatusCode.OK))
                return self.span_context.__exit__(exc_type, exc_val, exc_tb)

        return SpanWithAttributes(span_context, attributes)

    return span_context


def create_child_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Any:
    """Create a nested span using the current trace context.

    This is an alias for ``create_span()`` used where child-span intent is part
    of the local code structure.

    Args:
        name: Span name.
        attributes: Optional attributes to attach to the created span.

    Returns:
        Span context manager returned by ``create_span()``.
    """
    return create_span(name, attributes)


# Initialize on module import
_TRACER = init_telemetry()
