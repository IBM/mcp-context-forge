# -*- coding: utf-8 -*-
"""Location: ./plugins/regex_filter/search_replace.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Simple example plugin for searching and replacing text.
This module loads configurations for plugins.
"""

# Standard
import logging
import re

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

# Initialize logging
logger = logging.getLogger(__name__)

# Try to import Rust-accelerated implementation
try:
    from regex_filter import SearchReplacePluginRust

    _RUST_AVAILABLE = True
    logger.info("🦀 Rust regex filter available - using high-performance implementation")
except ImportError as e:
    _RUST_AVAILABLE = False
    SearchReplacePluginRust = None  # type: ignore
    logger.debug(f"Rust regex filter not available (will use Python): {e}")
except Exception as e:
    _RUST_AVAILABLE = False
    SearchReplacePluginRust = None  # type: ignore
    logger.warning(f"⚠️  Unexpected error loading Rust module: {e}", exc_info=True)


class SearchReplace(BaseModel):
    """Search and replace pattern configuration.

    Attributes:
        search: Regular expression pattern to search for.
        replace: Replacement text.
    """

    search: str
    replace: str

    def validate_pattern(self) -> tuple[bool, str | None]:
        """Validate that the regex pattern is valid in Python.

        Returns:
            Tuple of (is_valid, error_message).
        """
        try:
            re.compile(self.search)
            return (True, None)
        except re.error as e:
            return (False, f"Invalid regex pattern '{self.search}': {e}")


class SearchReplaceConfig(BaseModel):
    """Configuration for search and replace plugin.

    Attributes:
        words: List of search and replace patterns to apply.
    """

    words: list[SearchReplace]

    def validate_all_patterns(self) -> list[str]:
        """Validate all regex patterns.

        Returns:
            List of error messages for invalid patterns (empty if all valid).
        """
        errors = []
        for idx, word in enumerate(self.words):
            is_valid, error_msg = word.validate_pattern()
            if not is_valid:
                errors.append(f"Pattern {idx}: {error_msg}")
        return errors

    def get_known_incompatibilities(self) -> list[str]:
        """Check for known Python/Rust regex incompatibilities.

        Returns:
            List of warning messages about potential incompatibilities.
        """
        warnings = []
        for idx, word in enumerate(self.words):
            pattern = word.search

            # Check for Python-specific named groups: (?P<name>...)
            if "(?P<" in pattern:
                warnings.append(f"Pattern {idx} '{pattern}': Uses Python-specific named groups (?P<name>...). Rust uses (?<name>...) syntax. Pattern may fail in Rust implementation.")

            # Check for lookbehind (not fully supported in Rust regex)
            if "(?<!" in pattern or "(?<=" in pattern:
                warnings.append(f"Pattern {idx} '{pattern}': Uses lookbehind assertions. Rust regex has limited lookbehind support. Pattern may fail in Rust implementation.")

            # Check for backreferences (different syntax)
            if r"\1" in pattern or r"\2" in pattern or r"\g<" in pattern:
                warnings.append(f"Pattern {idx} '{pattern}': Uses backreferences. Syntax differs between Python and Rust. Verify compatibility.")

        return warnings


def _apply_patterns(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
    """Apply regex patterns to text using Python implementation.

    Args:
        text: Text to process.
        patterns: List of (compiled_pattern, replacement) tuples.

    Returns:
        Modified text with all patterns applied.
    """
    result = text
    for pattern, replacement in patterns:
        result = pattern.sub(replacement, result)
    return result


def _process_container(container: any, cfg: SearchReplaceConfig, patterns: list[tuple[re.Pattern[str], str]], use_rust: bool = True) -> tuple[bool, any]:
    """Process container with search/replace patterns.

    Args:
        container: Container to process (str, dict, list, or other).
        cfg: Search/replace configuration.
        patterns: Compiled regex patterns for Python fallback.
        use_rust: Whether to use Rust implementation if available.

    Returns:
        Tuple of (modified, new_container).
    """
    # Use Rust implementation if available and requested
    if use_rust and _RUST_AVAILABLE and SearchReplacePluginRust is not None:
        try:
            # Pass Pydantic config directly - Rust extracts attributes
            rust_plugin = SearchReplacePluginRust({"words": [{"search": w.search, "replace": w.replace} for w in cfg.words]})
            return rust_plugin.process_nested(container)
        except Exception as e:
            logger.warning(f"Rust processing failed, falling back to Python: {e}")
            # Fall through to Python implementation

    # Python implementation
    if isinstance(container, str):
        result = _apply_patterns(container, patterns)
        return (result != container, result)
    if isinstance(container, dict):
        modified = False
        new_dict = {}
        for key, value in container.items():
            val_modified, new_value = _process_container(value, cfg, patterns, use_rust=False)
            if val_modified:
                modified = True
            new_dict[key] = new_value
        return (modified, new_dict)
    if isinstance(container, list):
        modified = False
        new_list = []
        for item in container:
            item_modified, new_item = _process_container(item, cfg, patterns, use_rust=False)
            if item_modified:
                modified = True
            new_list.append(new_item)
        return (modified, new_list)
    return (False, container)


class SearchReplacePlugin(Plugin):
    """Example search replace plugin."""

    def __init__(self, config: PluginConfig):
        """Initialize the search and replace plugin.

        Args:
            config: Plugin configuration containing search/replace patterns.

        Raises:
            ValueError: If any regex patterns are invalid or incompatible.
        """
        super().__init__(config)
        self._srconfig = SearchReplaceConfig.model_validate(self._config.config)

        # Validate all patterns
        validation_errors = self._srconfig.validate_all_patterns()
        if validation_errors:
            error_msg = "Invalid regex patterns detected:\n" + "\n".join(validation_errors)
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Check for known incompatibilities
        compatibility_warnings = self._srconfig.get_known_incompatibilities()
        if compatibility_warnings:
            warning_msg = "Potential Python/Rust regex incompatibilities detected:\n" + "\n".join(compatibility_warnings)
            logger.warning(warning_msg)
            logger.warning("These patterns may work in one implementation but fail in the other.")

        # Set implementation type based on Rust availability
        if _RUST_AVAILABLE:
            self.implementation = "Rust"
            logger.info("🦀 SearchReplacePlugin initialized with Rust acceleration")
        else:
            self.implementation = "Python"
            logger.info("🐍 SearchReplacePlugin initialized with Python implementation")

        # Precompile regex patterns for Python implementation
        # All patterns are now validated, so compilation should succeed
        self.__patterns = []
        for word in self._srconfig.words:
            compiled_pattern = re.compile(word.search)
            self.__patterns.append((compiled_pattern, word.replace))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if payload.args:
            modified, new_args = _process_container(payload.args, self._srconfig, self.__patterns)
            if modified:
                payload.args = new_args
        return PromptPrehookResult(modified_payload=payload)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        if payload.result.messages:
            for index, message in enumerate(payload.result.messages):
                modified, new_text = _process_container(message.content.text, self._srconfig, self.__patterns)
                if modified:
                    payload.result.messages[index].content.text = new_text
        return PromptPosthookResult(modified_payload=payload)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        if payload.args:
            modified, new_args = _process_container(payload.args, self._srconfig, self.__patterns)
            if modified:
                payload.args = new_args
        return ToolPreInvokeResult(modified_payload=payload)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        if payload.result:
            modified, new_result = _process_container(payload.result, self._srconfig, self.__patterns)
            if modified:
                payload.result = new_result
        return ToolPostInvokeResult(modified_payload=payload)
