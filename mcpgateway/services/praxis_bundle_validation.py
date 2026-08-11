"""Strict parsing and cross-document validation for Praxis bundles."""

from enum import StrEnum, unique
from typing import assert_never

from pydantic import ValidationError

from mcpgateway.services.praxis_bundle_models import PraxisBundleDocument, PraxisCpexDocument
from mcpgateway.services.praxis_config_models import PraxisRenderedDocument


@unique
class PraxisBundleRenderErrorCode(StrEnum):
    """Stable sanitized renderer refusal categories."""

    UNKNOWN_FILTER = "unknown_filter"
    DANGLING_CONFIG_PATH = "dangling_config_path"
    DANGLING_REFERENCE = "dangling_reference"
    EMPTY_ROUTE = "empty_route"
    MISSING_TERMINAL_DENY = "missing_terminal_deny"
    DUPLICATE_PLUGIN = "duplicate_plugin"
    DUPLICATE_ROUTE = "duplicate_route"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    NON_FAIL_SECURITY_PLUGIN = "non_fail_security_plugin"
    INCOMPATIBLE_OUTPUT_MODEL = "incompatible_output_model"
    CREDENTIAL_MATERIAL = "credential_material"
    INVALID_DOCUMENT = "invalid_document"


class PraxisBundleRenderError(ValueError):
    """Sanitized failure that does not retain rejected document values."""

    __slots__ = ("code",)

    def __init__(self, code: PraxisBundleRenderErrorCode) -> None:
        """Retain only a stable refusal category."""
        super().__init__(code.value)
        self.code = code

    def __str__(self) -> str:
        """Return a fixed operator-facing refusal message."""
        return f"Praxis bundle render failed: {self.code.value}"


def _validation_code(error: ValidationError) -> PraxisBundleRenderErrorCode:
    issue = error.errors(include_url=False, include_context=False, include_input=False)[0]
    error_type = issue["type"]
    custom = {
        "credential_material": PraxisBundleRenderErrorCode.CREDENTIAL_MATERIAL,
        "dangling_reference": PraxisBundleRenderErrorCode.DANGLING_REFERENCE,
        "duplicate_plugin": PraxisBundleRenderErrorCode.DUPLICATE_PLUGIN,
        "duplicate_route": PraxisBundleRenderErrorCode.DUPLICATE_ROUTE,
        "empty_route": PraxisBundleRenderErrorCode.EMPTY_ROUTE,
        "incompatible_output_model": PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL,
        "missing_terminal_deny": PraxisBundleRenderErrorCode.MISSING_TERMINAL_DENY,
        "non_fail_security_plugin": PraxisBundleRenderErrorCode.NON_FAIL_SECURITY_PLUGIN,
        "unsupported_capability": PraxisBundleRenderErrorCode.UNSUPPORTED_CAPABILITY,
    }
    if error_type in custom:
        return custom[error_type]
    location = tuple(str(part) for part in issue["loc"])
    if error_type == "literal_error" and "filter" in location:
        return PraxisBundleRenderErrorCode.UNKNOWN_FILTER
    if ("routes" in location or "filters" in location) and error_type in {"too_short", "missing", "tuple_type"}:
        return PraxisBundleRenderErrorCode.EMPTY_ROUTE
    return PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL


def _parse(content: bytes, cpex: bool) -> PraxisBundleDocument | PraxisCpexDocument | PraxisBundleRenderErrorCode:
    try:
        return PraxisCpexDocument.model_validate_json(content) if cpex else PraxisBundleDocument.model_validate_json(content)
    except ValidationError as error:
        return _validation_code(error)


def _unwrap(outcome: PraxisBundleDocument | PraxisCpexDocument | PraxisBundleRenderErrorCode) -> PraxisBundleDocument | PraxisCpexDocument:
    match outcome:
        case PraxisBundleDocument() | PraxisCpexDocument():
            return outcome
        case PraxisBundleRenderErrorCode():
            raise PraxisBundleRenderError(outcome) from None
        case unreachable:
            assert_never(unreachable)


def parse_praxis_document(content: bytes) -> PraxisBundleDocument:
    """Strictly parse one generated root document without retaining bad input."""
    match _unwrap(_parse(content, False)):
        case PraxisBundleDocument() as parsed:
            return parsed
        case PraxisCpexDocument():
            raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)
        case unreachable:
            assert_never(unreachable)


def parse_cpex_document(content: bytes) -> PraxisCpexDocument:
    """Strictly parse one generated CPEX document without retaining bad input."""
    match _unwrap(_parse(content, True)):
        case PraxisCpexDocument() as parsed:
            return parsed
        case PraxisBundleDocument():
            raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)
        case unreachable:
            assert_never(unreachable)


def validate_bundle_documents(documents: tuple[PraxisRenderedDocument, ...]) -> tuple[PraxisRenderedDocument, ...]:
    """Validate ordering, strict models, references, and immutable relative paths."""
    ordered = tuple(sorted(documents, key=lambda document: document.path))
    if documents != ordered or len({document.path for document in documents}) != len(documents):
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)
    roots = tuple(document for document in documents if document.path == "praxis.yaml")
    cpex_documents = tuple(document for document in documents if document.path.startswith("cpex/"))
    if len(roots) != 1 or len(cpex_documents) != len(documents) - 1:
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.INCOMPATIBLE_OUTPUT_MODEL)
    root = parse_praxis_document(roots[0].content)
    actual = tuple(document.path for document in cpex_documents)
    dispatcher = root.filter_chains[0].filters[1]
    mappings = dispatcher.policies or ()
    if tuple(mapping.config_path for mapping in mappings) != actual:
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.DANGLING_CONFIG_PATH)
    if any(not mapping.config_path.endswith(f"--{mapping.server_id}.yaml") for mapping in mappings):
        raise PraxisBundleRenderError(PraxisBundleRenderErrorCode.DANGLING_CONFIG_PATH)
    for document in cpex_documents:
        parse_cpex_document(document.content)
    return ordered


__all__ = (
    "PraxisBundleRenderError",
    "PraxisBundleRenderErrorCode",
    "parse_cpex_document",
    "parse_praxis_document",
    "validate_bundle_documents",
)
