# -*- coding: utf-8 -*-
"""PII Filter Plugin for MCP Gateway.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This plugin detects and masks Personally Identifiable Information (PII) in prompts
and their responses, including SSNs, credit cards, emails, phone numbers, and more.
"""

# Standard
import re
from enum import Enum
from typing import Optional, Pattern, Dict, List, Tuple
import logging

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework.base import Plugin
from mcpgateway.plugins.framework.models import PluginConfig, PluginViolation
from mcpgateway.plugins.framework.plugin_types import (
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
)

logger = logging.getLogger(__name__)


class PIIType(str, Enum):
    """Types of PII that can be detected."""

    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    EMAIL = "email"
    PHONE = "phone"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"
    PASSPORT = "passport"
    DRIVER_LICENSE = "driver_license"
    BANK_ACCOUNT = "bank_account"
    MEDICAL_RECORD = "medical_record"
    AWS_KEY = "aws_key"
    API_KEY = "api_key"
    CUSTOM = "custom"


class MaskingStrategy(str, Enum):
    """Strategies for masking detected PII."""

    REDACT = "redact"  # Replace with [REDACTED]
    PARTIAL = "partial"  # Show partial info (e.g., ***-**-1234)
    HASH = "hash"  # Replace with hash
    TOKENIZE = "tokenize"  # Replace with token
    REMOVE = "remove"  # Remove entirely


class PIIPattern(BaseModel):
    """Configuration for a PII pattern."""

    type: PIIType
    pattern: str
    description: str
    mask_strategy: MaskingStrategy = MaskingStrategy.REDACT
    enabled: bool = True


class PIIFilterConfig(BaseModel):
    """Configuration for the PII Filter plugin."""

    # Enable/disable detection for specific PII types
    detect_ssn: bool = Field(default=True, description="Detect Social Security Numbers")
    detect_credit_card: bool = Field(default=True, description="Detect credit card numbers")
    detect_email: bool = Field(default=True, description="Detect email addresses")
    detect_phone: bool = Field(default=True, description="Detect phone numbers")
    detect_ip_address: bool = Field(default=True, description="Detect IP addresses")
    detect_date_of_birth: bool = Field(default=True, description="Detect dates of birth")
    detect_passport: bool = Field(default=True, description="Detect passport numbers")
    detect_driver_license: bool = Field(default=True, description="Detect driver's license numbers")
    detect_bank_account: bool = Field(default=True, description="Detect bank account numbers")
    detect_medical_record: bool = Field(default=True, description="Detect medical record numbers")
    detect_aws_keys: bool = Field(default=True, description="Detect AWS access keys")
    detect_api_keys: bool = Field(default=True, description="Detect generic API keys")

    # Masking configuration
    default_mask_strategy: MaskingStrategy = Field(
        default=MaskingStrategy.REDACT,
        description="Default masking strategy"
    )
    redaction_text: str = Field(default="[REDACTED]", description="Text to use for redaction")

    # Behavior configuration
    block_on_detection: bool = Field(
        default=False,
        description="Block request if PII is detected"
    )
    log_detections: bool = Field(default=True, description="Log PII detections")
    include_detection_details: bool = Field(
        default=True,
        description="Include detection details in metadata"
    )

    # Custom patterns
    custom_patterns: List[PIIPattern] = Field(
        default_factory=list,
        description="Custom PII patterns to detect"
    )

    # Whitelist configuration
    whitelist_patterns: List[str] = Field(
        default_factory=list,
        description="Patterns to exclude from PII detection"
    )


class PIIDetector:
    """Core PII detection logic."""

    def __init__(self, config: PIIFilterConfig):
        """Initialize the PII detector with configuration.

        Args:
            config: PII filter configuration
        """
        self.config = config
        self.patterns: Dict[PIIType, List[Tuple[Pattern, MaskingStrategy]]] = {}
        self._compile_patterns()
        self._compile_whitelist()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for PII detection."""
        patterns = []

        # Social Security Number patterns
        if self.config.detect_ssn:
            patterns.append(PIIPattern(
                type=PIIType.SSN,
                pattern=r'\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b',
                description="US Social Security Number",
                mask_strategy=MaskingStrategy.PARTIAL
            ))

        # Credit Card patterns (basic validation for common formats)
        if self.config.detect_credit_card:
            patterns.append(PIIPattern(
                type=PIIType.CREDIT_CARD,
                pattern=r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
                description="Credit card number",
                mask_strategy=MaskingStrategy.PARTIAL
            ))

        # Email patterns
        if self.config.detect_email:
            patterns.append(PIIPattern(
                type=PIIType.EMAIL,
                pattern=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                description="Email address",
                mask_strategy=MaskingStrategy.PARTIAL
            ))

        # Phone number patterns (US and international)
        if self.config.detect_phone:
            patterns.extend([
                PIIPattern(
                    type=PIIType.PHONE,
                    pattern=r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
                    description="US phone number",
                    mask_strategy=MaskingStrategy.PARTIAL
                ),
                PIIPattern(
                    type=PIIType.PHONE,
                    pattern=r'\b\+?[1-9]\d{1,14}\b',
                    description="International phone number",
                    mask_strategy=MaskingStrategy.PARTIAL
                )
            ])

        # IP Address patterns (IPv4 and IPv6)
        if self.config.detect_ip_address:
            patterns.extend([
                PIIPattern(
                    type=PIIType.IP_ADDRESS,
                    pattern=r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
                    description="IPv4 address",
                    mask_strategy=MaskingStrategy.REDACT
                ),
                PIIPattern(
                    type=PIIType.IP_ADDRESS,
                    pattern=r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b',
                    description="IPv6 address",
                    mask_strategy=MaskingStrategy.REDACT
                )
            ])

        # Date of Birth patterns
        if self.config.detect_date_of_birth:
            patterns.extend([
                PIIPattern(
                    type=PIIType.DATE_OF_BIRTH,
                    pattern=r'\b(?:DOB|Date of Birth|Born|Birthday)[:\s]+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b',
                    description="Date of birth with label",
                    mask_strategy=MaskingStrategy.REDACT
                ),
                PIIPattern(
                    type=PIIType.DATE_OF_BIRTH,
                    pattern=r'\b(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])[-/](?:19|20)\d{2}\b',
                    description="Date in MM/DD/YYYY format",
                    mask_strategy=MaskingStrategy.REDACT
                )
            ])

        # Passport patterns
        if self.config.detect_passport:
            patterns.append(PIIPattern(
                type=PIIType.PASSPORT,
                pattern=r'\b[A-Z]{1,2}\d{6,9}\b',
                description="Passport number",
                mask_strategy=MaskingStrategy.REDACT
            ))

        # Driver's License patterns (US states)
        if self.config.detect_driver_license:
            patterns.append(PIIPattern(
                type=PIIType.DRIVER_LICENSE,
                pattern=r'\b(?:DL|License|Driver\'?s? License)[#:\s]+[A-Z0-9]{5,20}\b',
                description="Driver's license number",
                mask_strategy=MaskingStrategy.REDACT
            ))

        # Bank Account patterns
        if self.config.detect_bank_account:
            patterns.extend([
                PIIPattern(
                    type=PIIType.BANK_ACCOUNT,
                    pattern=r'\b\d{8,17}\b',  # Generic bank account
                    description="Bank account number",
                    mask_strategy=MaskingStrategy.REDACT
                ),
                PIIPattern(
                    type=PIIType.BANK_ACCOUNT,
                    pattern=r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:\d{3})?\b',  # IBAN
                    description="IBAN",
                    mask_strategy=MaskingStrategy.PARTIAL
                )
            ])

        # Medical Record patterns
        if self.config.detect_medical_record:
            patterns.append(PIIPattern(
                type=PIIType.MEDICAL_RECORD,
                pattern=r'\b(?:MRN|Medical Record)[#:\s]+[A-Z0-9]{6,12}\b',
                description="Medical record number",
                mask_strategy=MaskingStrategy.REDACT
            ))

        # AWS Access Key patterns
        if self.config.detect_aws_keys:
            patterns.extend([
                PIIPattern(
                    type=PIIType.AWS_KEY,
                    pattern=r'\bAKIA[0-9A-Z]{16}\b',
                    description="AWS Access Key ID",
                    mask_strategy=MaskingStrategy.REDACT
                ),
                PIIPattern(
                    type=PIIType.AWS_KEY,
                    pattern=r'\b[A-Za-z0-9/+=]{40}\b',
                    description="AWS Secret Access Key",
                    mask_strategy=MaskingStrategy.REDACT
                )
            ])

        # Generic API Key patterns
        if self.config.detect_api_keys:
            patterns.append(PIIPattern(
                type=PIIType.API_KEY,
                pattern=r'\b(?:api[_-]?key|apikey|api_token|access[_-]?token)[:\s]+[\'"]?[A-Za-z0-9\-_]{20,}[\'"]?\b',
                description="Generic API key",
                mask_strategy=MaskingStrategy.REDACT
            ))

        # Add custom patterns
        patterns.extend(self.config.custom_patterns)

        # Compile patterns by type
        for pattern_config in patterns:
            if pattern_config.enabled:
                compiled = re.compile(pattern_config.pattern, re.IGNORECASE)
                if pattern_config.type not in self.patterns:
                    self.patterns[pattern_config.type] = []
                self.patterns[pattern_config.type].append(
                    (compiled, pattern_config.mask_strategy)
                )

    def _compile_whitelist(self) -> None:
        """Compile whitelist patterns."""
        self.whitelist_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.config.whitelist_patterns
        ]

    def _is_whitelisted(self, text: str, match_start: int, match_end: int) -> bool:
        """Check if a matched pattern is whitelisted.

        Args:
            text: The full text
            match_start: Start position of the match
            match_end: End position of the match

        Returns:
            True if the match is whitelisted
        """
        match_text = text[match_start:match_end]
        for pattern in self.whitelist_patterns:
            if pattern.search(match_text):
                return True
        return False

    def detect(self, text: str) -> Dict[PIIType, List[Dict]]:
        """Detect PII in text.

        Args:
            text: Text to scan for PII

        Returns:
            Dictionary of detected PII by type
        """
        detections = {}

        for pii_type, pattern_list in self.patterns.items():
            type_detections = []
            seen_ranges = []  # Track ranges we've already detected

            for pattern, mask_strategy in pattern_list:
                for match in pattern.finditer(text):
                    if not self._is_whitelisted(text, match.start(), match.end()):
                        # Check if this overlaps with any existing detection
                        overlaps = False
                        for start, end in seen_ranges:
                            if (match.start() >= start and match.start() < end) or \
                            (match.end() > start and match.end() <= end) or \
                            (match.start() <= start and match.end() >= end):
                                overlaps = True
                                break

                        if not overlaps:
                            type_detections.append({
                                'value': match.group(),
                                'start': match.start(),
                                'end': match.end(),
                                'mask_strategy': mask_strategy
                            })
                            seen_ranges.append((match.start(), match.end()))

            if type_detections:
                detections[pii_type] = type_detections

        return detections

    def mask(self, text: str, detections: Dict[PIIType, List[Dict]]) -> str:
        """Mask detected PII in text.

        Args:
            text: Original text
            detections: Dictionary of detected PII

        Returns:
            Text with PII masked
        """
        if not detections:
            return text

        # Sort all detections by position (reverse order for replacement)
        all_detections = []
        for pii_type, items in detections.items():
            for item in items:
                item['type'] = pii_type
                all_detections.append(item)

        all_detections.sort(key=lambda x: x['start'], reverse=True)

        # Apply masking
        masked_text = text
        for detection in all_detections:
            strategy = detection.get('mask_strategy', self.config.default_mask_strategy)
            masked_value = self._apply_mask(
                detection['value'],
                detection['type'],
                strategy
            )
            masked_text = (
                masked_text[:detection['start']] +
                masked_value +
                masked_text[detection['end']:]
            )

        return masked_text

    def _apply_mask(self, value: str, pii_type: PIIType, strategy: MaskingStrategy) -> str:
        """Apply masking strategy to a value.

        Args:
            value: Value to mask
            pii_type: Type of PII
            strategy: Masking strategy to apply

        Returns:
            Masked value
        """
        if strategy == MaskingStrategy.REDACT:
            return self.config.redaction_text

        elif strategy == MaskingStrategy.PARTIAL:
            # Show partial information based on type
            if pii_type == PIIType.SSN:
                if len(value) >= 4:
                    return f"***-**-{value[-4:]}"
                return self.config.redaction_text

            elif pii_type == PIIType.CREDIT_CARD:
                if len(value) >= 4:
                    return f"****-****-****-{value[-4:]}"
                return self.config.redaction_text

            elif pii_type == PIIType.EMAIL:
                parts = value.split('@')
                if len(parts) == 2:
                    name = parts[0]
                    if len(name) > 2:
                        return f"{name[0]}***{name[-1]}@{parts[1]}"
                    return f"***@{parts[1]}"
                return self.config.redaction_text

            elif pii_type == PIIType.PHONE:
                if len(value) >= 4:
                    return f"***-***-{value[-4:]}"
                return self.config.redaction_text

            else:
                # For other types, show first and last characters
                if len(value) > 2:
                    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"
                return self.config.redaction_text

        elif strategy == MaskingStrategy.HASH:
            import hashlib
            return f"[HASH:{hashlib.sha256(value.encode()).hexdigest()[:8]}]"

        elif strategy == MaskingStrategy.TOKENIZE:
            import uuid
            # In production, you'd store the mapping
            return f"[TOKEN:{uuid.uuid4().hex[:8]}]"

        elif strategy == MaskingStrategy.REMOVE:
            return ""

        return self.config.redaction_text


class PIIFilterPlugin(Plugin):
    """PII Filter plugin for detecting and masking sensitive information."""

    def __init__(self, config: PluginConfig):
        """Initialize the PII filter plugin.

        Args:
            config: Plugin configuration
        """
        super().__init__(config)
        self.pii_config = PIIFilterConfig.model_validate(self._config.config)
        self.detector = PIIDetector(self.pii_config)
        self.detection_count = 0
        self.masked_count = 0

    async def prompt_pre_fetch(
        self,
        payload: PromptPrehookPayload,
        context: PluginContext
    ) -> PromptPrehookResult:
        """Process prompt before retrieval to detect and mask PII.

        Args:
            payload: The prompt payload
            context: Plugin context

        Returns:
            Result with masked PII or violation if blocking
        """
        if not payload.args:
            return PromptPrehookResult()

        all_detections = {}
        modified_args = {}

        # Process each argument
        for key, value in payload.args.items():
            if isinstance(value, str):
                detections = self.detector.detect(value)

                if detections:
                    all_detections[key] = detections

                    if self.pii_config.log_detections:
                        logger.warning(
                            f"PII detected in prompt argument '{key}': "
                            f"{', '.join(detections.keys())}"
                        )

                    if self.pii_config.block_on_detection:
                        violation = PluginViolation(
                            reason="PII detected in prompt",
                            description=f"Sensitive information detected in argument '{key}'",
                            code="PII_DETECTED",
                            details={
                                "field": key,
                                "types": list(detections.keys()),
                                "count": sum(len(items) for items in detections.values())
                            }
                        )
                        return PromptPrehookResult(
                            continue_processing=False,
                            violation=violation
                        )

                    # Mask the PII
                    masked_value = self.detector.mask(value, detections)
                    modified_args[key] = masked_value
                    self.masked_count += sum(len(items) for items in detections.values())
                else:
                    modified_args[key] = value
            else:
                modified_args[key] = value

        # Update context with detection metadata
        if all_detections and self.pii_config.include_detection_details:
            context.metadata["pii_detections"] = {
                "pre_fetch": {
                    "detected": True,
                    "fields": list(all_detections.keys()),
                    "types": list(set(
                        pii_type
                        for field_detections in all_detections.values()
                        for pii_type in field_detections.keys()
                    )),
                    "total_count": sum(
                        len(items)
                        for field_detections in all_detections.values()
                        for items in field_detections.values()
                    )
                }
            }

        # Return modified payload if PII was masked
        if all_detections:
            return PromptPrehookResult(
                modified_payload=PromptPrehookPayload(
                    name=payload.name,
                    args=modified_args
                )
            )

        return PromptPrehookResult()

    async def prompt_post_fetch(
        self,
        payload: PromptPosthookPayload,
        context: PluginContext
    ) -> PromptPosthookResult:
        """Process prompt after rendering to detect and mask PII in response.

        Args:
            payload: The prompt result payload
            context: Plugin context

        Returns:
            Result with masked PII in messages
        """
        if not payload.result.messages:
            return PromptPosthookResult()

        modified = False
        all_detections = {}

        # Process each message
        for message in payload.result.messages:
            if message.content and hasattr(message.content, 'text'):
                text = message.content.text
                detections = self.detector.detect(text)

                if detections:
                    all_detections[f"message_{message.role}"] = detections

                    if self.pii_config.log_detections:
                        logger.warning(
                            f"PII detected in {message.role} message: "
                            f"{', '.join(detections.keys())}"
                        )

                    # Mask the PII
                    masked_text = self.detector.mask(text, detections)
                    message.content.text = masked_text
                    modified = True
                    self.masked_count += sum(len(items) for items in detections.values())

        # Update context with post-fetch detection metadata
        if all_detections and self.pii_config.include_detection_details:
            if "pii_detections" not in context.metadata:
                context.metadata["pii_detections"] = {}

            context.metadata["pii_detections"]["post_fetch"] = {
                "detected": True,
                "messages": list(all_detections.keys()),
                "types": list(set(
                    pii_type
                    for msg_detections in all_detections.values()
                    for pii_type in msg_detections.keys()
                )),
                "total_count": sum(
                    len(items)
                    for msg_detections in all_detections.values()
                    for items in msg_detections.values()
                )
            }

        # Add summary statistics
        context.metadata["pii_filter_stats"] = {
            "total_detections": self.detection_count,
            "total_masked": self.masked_count
        }

        if modified:
            return PromptPosthookResult(modified_payload=payload)

        return PromptPosthookResult()

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info(
            f"PII Filter plugin shutting down. "
            f"Total masked: {self.masked_count} items"
        )
