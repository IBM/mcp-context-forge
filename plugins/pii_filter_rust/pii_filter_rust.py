# -*- coding: utf-8 -*-
"""Rust-backed PII Filter plugin.

The Rust plugin is intentionally implemented as its own plugin path so its
logging, configuration contract, and behavior can evolve independently from the
Python PII filter plugin.
"""

# Standard
import logging
from collections.abc import Mapping
from typing import Any

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)

try:
    from pii_filter_rust import PIIDetectorRust as RustPIIDetector

    RUST_AVAILABLE = True
except ImportError as e:
    RustPIIDetector = None
    RUST_AVAILABLE = False
    logger.debug("Rust PII filter not available: %s", e)
except Exception as e:
    RustPIIDetector = None
    RUST_AVAILABLE = False
    logger.warning("Unexpected error loading Rust PII module: %s", e, exc_info=True)


class RustPIIFilterPlugin(Plugin):
    """PII filter plugin backed by the Rust detector."""

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        if not RUST_AVAILABLE or RustPIIDetector is None:
            raise ImportError("Rust PII plugin requires the `pii_filter_rust` package to be installed")
        raw_config = self._config.config or {}
        if not isinstance(raw_config, Mapping):
            raise TypeError(f"RustPIIFilterPlugin config must be a mapping, got {type(raw_config).__name__}")
        self.rust_config = dict(raw_config)
        self.detector = RustPIIDetector(self.rust_config)
        self.implementation = "Rust"
        self.detection_count = 0
        self.masked_count = 0
        logger.info("RustPIIFilterPlugin initialized")

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Detect and mask PII in prompt args before rendering."""
        if not payload.args:
            return PromptPrehookResult()

        all_detections: dict[str, dict[str, list[dict[str, Any]]]] = {}
        modified_args = {}

        for key, value in payload.args.items():
            if not isinstance(value, str):
                modified_args[key] = value
                continue

            detections = self.detector.detect(value)
            if not detections:
                modified_args[key] = value
                continue

            all_detections[key] = detections
            self._log_detection_event("prompt_pre_fetch", key, detections)

            if self._cfg_bool("block_on_detection", False):
                return PromptPrehookResult(continue_processing=False, violation=self._build_prompt_violation(key, detections))

            modified_args[key] = self.detector.mask(value, detections)
            self.masked_count += self._count_detections(detections)

        self._store_prompt_metadata(context, "pre_fetch", all_detections)

        if all_detections:
            return PromptPrehookResult(modified_payload=PromptPrehookPayload(prompt_id=payload.prompt_id, args=modified_args))

        return PromptPrehookResult()

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Detect and mask PII in prompt messages."""
        if not payload.result.messages:
            return PromptPosthookResult()

        all_detections: dict[str, dict[str, list[dict[str, Any]]]] = {}
        modified = False

        for message in payload.result.messages:
            if not message.content or not hasattr(message.content, "text"):
                continue

            text = message.content.text
            detections = self.detector.detect(text)
            if not detections:
                continue

            path = f"message_{message.role}"
            all_detections[path] = detections
            self._log_detection_event("prompt_post_fetch", path, detections)

            if self._cfg_bool("block_on_detection", False):
                return PromptPosthookResult(
                    continue_processing=False,
                    violation=self._build_violation(
                        reason="PII detected in prompt response",
                        description="Detected PII in rendered prompt output",
                        code="PII_DETECTED",
                        path=path,
                        detections=detections,
                    ),
                )

            message.content.text = self.detector.mask(text, detections)
            self.masked_count += self._count_detections(detections)
            modified = True

        self._store_prompt_metadata(context, "post_fetch", all_detections, metadata_key="messages")
        self._store_stats(context)

        if modified:
            return PromptPosthookResult(modified_payload=payload)

        return PromptPosthookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Detect and mask PII in tool arguments."""
        if not payload.args:
            return ToolPreInvokeResult()

        if self._cfg_bool("block_on_detection", False):
            detections = self._inspect_nested(payload.args)
            detection_types = self._flatten_detection_types(detections)
            if detection_types:
                self._log_detection_event("tool_pre_invoke", "args", detections)
                return ToolPreInvokeResult(
                    continue_processing=False,
                    violation=self._build_violation(
                        reason="PII detected in tool arguments",
                        description="Detected PII in tool arguments",
                        code="PII_DETECTED_IN_TOOL_ARGS",
                        path="args",
                        detections=detections,
                    ),
                )
            return ToolPreInvokeResult()

        modified, new_args, detections = self.detector.process_nested(payload.args, "args")
        detection_types = self._flatten_detection_types(detections)
        if detection_types:
            self._log_detection_event("tool_pre_invoke", "args", detections)

        if modified:
            self.masked_count += self._count_detections(detections)
        self._store_tool_metadata(context, "tool_pre_invoke", "arguments", detections)
        self._store_stats(context)

        if modified:
            return ToolPreInvokeResult(modified_payload=payload.model_copy(update={"args": new_args}))

        return ToolPreInvokeResult()

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Detect and mask PII in tool results."""
        if payload.result is None:
            return ToolPostInvokeResult()

        if not isinstance(payload.result, (str, dict, list)):
            return ToolPostInvokeResult()

        if self._cfg_bool("block_on_detection", False):
            detections = self._inspect_nested(payload.result)
            detection_types = self._flatten_detection_types(detections)
            if detection_types:
                self._log_detection_event("tool_post_invoke", "result", detections)
                return ToolPostInvokeResult(
                    continue_processing=False,
                    violation=self._build_violation(
                        reason="PII detected in tool result",
                        description="Detected PII in tool output",
                        code="PII_DETECTED_IN_TOOL_RESULT",
                        path="result",
                        detections=detections,
                    ),
                )
            return ToolPostInvokeResult()

        modified, new_result, detections = self.detector.process_nested(payload.result, "result")
        detection_types = self._flatten_detection_types(detections)
        if detection_types:
            self._log_detection_event("tool_post_invoke", "result", detections)

        if modified:
            self.masked_count += self._count_detections(detections)
        self._store_tool_metadata(context, "tool_post_invoke", "fields", detections)
        self._store_stats(context)

        if modified:
            return ToolPostInvokeResult(modified_payload=payload.model_copy(update={"result": new_result}))

        return ToolPostInvokeResult()

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info(
            "RustPIIFilterPlugin shutting down with detection_count=%s masked_count=%s",
            self.detection_count,
            self.masked_count,
        )

    def _log_detection_event(self, operation: str, path: str, detections: dict[str, list[dict[str, Any]]]) -> None:
        """Log only safe detection metadata for the Rust plugin path."""
        if not self._cfg_bool("log_detections", True) or not detections:
            return
        detection_count = self._count_detections(detections)
        pii_types = ",".join(self._flatten_detection_types(detections))
        self.detection_count += detection_count
        logger.warning(
            "event=rust_pii_filter_detection operation=%s path=%s pii_types=%s detection_count=%s block_on_detection=%s",
            operation,
            path,
            pii_types,
            detection_count,
            self._cfg_bool("block_on_detection", False),
        )

    def _build_prompt_violation(self, key: str, detections: dict[str, list[dict[str, Any]]]) -> PluginViolation:
        return self._build_violation(
            reason="PII detected in prompt",
            description=f"Sensitive information detected in argument '{key}'",
            code="PII_DETECTED",
            path=key,
            detections=detections,
        )

    def _build_violation(self, reason: str, description: str, code: str, path: str, detections: dict[str, list[dict[str, Any]]]) -> PluginViolation:
        return PluginViolation(
            reason=reason,
            description=description,
            code=code,
            details={
                "field": path,
                "types": self._flatten_detection_types(detections),
                "count": self._count_detections(detections),
            },
        )

    def _store_prompt_metadata(
        self,
        context: PluginContext,
        stage: str,
        all_detections: dict[str, dict[str, list[dict[str, Any]]]],
        metadata_key: str = "fields",
    ) -> None:
        if not all_detections or not self._cfg_bool("include_detection_details", True):
            return
        if "pii_detections" not in context.metadata:
            context.metadata["pii_detections"] = {}
        context.metadata["pii_detections"][stage] = {
            "detected": True,
            metadata_key: list(all_detections.keys()),
            "types": sorted({pii_type for detections in all_detections.values() for pii_type in detections.keys()}),
            "total_count": sum(self._count_detections(detections) for detections in all_detections.values()),
        }

    def _store_tool_metadata(self, context: PluginContext, stage: str, metadata_key: str, detections: dict[str, list[dict[str, Any]]]) -> None:
        if not detections or not self._cfg_bool("include_detection_details", True):
            return
        if "pii_detections" not in context.metadata:
            context.metadata["pii_detections"] = {}
        context.metadata["pii_detections"][stage] = {
            "detected": True,
            metadata_key: ["result" if stage == "tool_post_invoke" else "args"],
            "types": self._flatten_detection_types(detections),
            "total_count": self._count_detections(detections),
        }

    def _store_stats(self, context: PluginContext) -> None:
        context.metadata["pii_filter_stats"] = {
            "total_detections": self.detection_count,
            "total_masked": self.masked_count,
        }

    @staticmethod
    def _count_detections(detections: dict[str, list[dict[str, Any]]]) -> int:
        return sum(len(items) for items in detections.values())

    @staticmethod
    def _flatten_detection_types(detections: dict[str, list[dict[str, Any]]]) -> list[str]:
        return sorted(detections.keys())

    def _cfg_bool(self, key: str, default: bool) -> bool:
        value = self.rust_config.get(key, default)
        if isinstance(value, bool):
            return value
        return default

    def _inspect_nested(self, data: Any) -> dict[str, list[dict[str, Any]]]:
        """Collect nested detections without invoking Rust's blocking mutation path."""
        aggregated: dict[str, list[dict[str, Any]]] = {}

        if isinstance(data, str):
            return self.detector.detect(data)

        if isinstance(data, Mapping):
            for value in data.values():
                self._merge_detections(aggregated, self._inspect_nested(value))
            return aggregated

        if isinstance(data, list):
            for item in data:
                self._merge_detections(aggregated, self._inspect_nested(item))

        return aggregated

    @staticmethod
    def _merge_detections(target: dict[str, list[dict[str, Any]]], incoming: dict[str, list[dict[str, Any]]]) -> None:
        for pii_type, items in incoming.items():
            target.setdefault(pii_type, []).extend(items)


__all__ = ["RUST_AVAILABLE", "RustPIIDetector", "RustPIIFilterPlugin"]
