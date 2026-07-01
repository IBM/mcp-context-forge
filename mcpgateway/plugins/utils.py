# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/utils.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateway-side plugin utilities.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from cpex.framework.extensions import Extensions, RequestExtension

logger = logging.getLogger(__name__)


def build_request_extensions() -> Optional[Extensions]:
    """Build a CPEX ``Extensions`` object carrying the currently active trace context.

    Reads the active trace_id/span_id from the observability ContextVars
    (``current_trace_id`` / ``current_span_id`` in ``mcpgateway.services.observability_service``,
    set by ``ObservabilityMiddleware`` for the lifetime of the request) and wraps them in a
    CPEX ``RequestExtension`` so plugin hook invocations (``invoke_hook(..., extensions=...)``)
    can correlate their execution with the originating HTTP request's trace/span.

    This is deliberately best-effort: it must never raise into the request path. If no trace
    is currently active (e.g. observability is disabled, or the call happens outside of a
    traced request such as a background task or test), or if anything unexpected goes wrong
    while building the extensions, ``None`` is returned so callers can pass it straight through
    to ``invoke_hook(extensions=...)`` without any special-casing.

    Note: the import of ``mcpgateway.services.observability_service`` is deliberately deferred
    to inside this function (rather than at module level) to avoid a circular import: that
    service module's package (``mcpgateway.services``) eagerly imports ``tool_service`` /
    ``prompt_service`` in its ``__init__.py``, both of which import this helper.

    Returns:
        An ``Extensions`` instance with a populated ``request`` field when a trace_id is
        active, otherwise ``None``.
    """
    try:
        # First-Party (deferred to avoid a circular import with mcpgateway.services.__init__)
        from mcpgateway.services.observability_service import current_span_id, current_trace_id  # pylint: disable=import-outside-toplevel

        trace_id = current_trace_id.get()
        if not trace_id:
            return None
        span_id = current_span_id.get()
        return Extensions(request=RequestExtension(trace_id=trace_id, span_id=span_id))
    except Exception:  # noqa: BLE001 - best-effort helper, must never raise into the request path
        logger.debug("Failed to build CPEX request Extensions from active trace context", exc_info=True)
        return None


def apply_attribute_mapping(attributes: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Apply attribute name mapping (renaming) to a dictionary of attributes.

    Args:
        attributes: Dictionary of attributes to rename.
        mapping: Dictionary mapping old attribute names to new names.

    Returns:
        New dictionary with renamed attributes.

    Example:
        >>> attrs = {"tool.name": "weather", "tool.version": "1.0"}
        >>> mapping = {"tool.name": "controls.artifact.name"}
        >>> apply_attribute_mapping(attrs, mapping)
        {'controls.artifact.name': 'weather', 'tool.version': '1.0'}
    """
    if not mapping:
        return dict(attributes)

    renamed_attributes = {}
    for old_name, value in attributes.items():
        new_name = mapping.get(old_name, old_name)
        renamed_attributes[new_name] = value

    logger.debug("Applied %d attribute name mappings", len(mapping))
    return renamed_attributes
