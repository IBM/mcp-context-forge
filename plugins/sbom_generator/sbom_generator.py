#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/sbom_generator.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Ayo
"""

# Standard
import logging
from typing import Any

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PluginViolationError,
)

# Local
from .config import SBOMGeneratorConfig
from .errors import (
    ExtractionError,
    GenerationError,
    SBOMGeneratorError,
    StorageError,
    ValidationError,
)
from .models import (
    ExtractionResult,
    LicensePolicy,
    SBOMDocument,
)

logger = logging.getLogger(__name__)


class SBOMGeneratorPlugin(Plugin):
    """SBOM Generator Plugin.

    Generates Software Bill of Materials (SBOM) for MCP servers using Syft
    for dependency extraction and CycloneDX/SPDX for SBOM generation.
    """

    def __init__(self, config: PluginConfig):
        """Initialize plugin."""
        super().__init__(config)

        try:
            self.plugin_config = SBOMGeneratorConfig(**config.config)
        except Exception as e:
            logger.error(f"Failed to parse SBOM generator config: {e}")
            raise ValidationError(f"Invalid plugin configuration: {e}")

        self.license_policy = LicensePolicy(
            blocked=self.plugin_config.license.blocked_licenses,
            flagged=self.plugin_config.license.warn_licenses,
        )

        logger.info(f"Initialized {self.config.name} v{self.config.version or '0.1.0'} " f"(format={self.plugin_config.syft.format})")

    async def assessment_post_scan(self, context: PluginContext, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate SBOM after MCP server assessment.

        Args:
            context: Plugin execution context with DB session
            payload: Assessment data including server metadata

        Returns:
            Dict with SBOM ID, component count, and license analysis

        Raises:
            PluginViolationError: For blocked licenses or storage failures
        """
        server_id = payload.get("server_id")
        if not server_id:
            raise ValueError("server_id required in assessment payload")

        logger.info(f"Starting SBOM generation for server: {server_id}")

        try:
            # Step 1: Extract dependencies
            extraction_result = await self._extract_dependencies(context, payload)

            if extraction_result.has_errors:
                logger.warning(f"Extraction completed with {len(extraction_result.errors)} errors")

            # Step 2: Generate SBOM document
            sbom_doc = await self._generate_sbom(context, extraction_result, payload)

            # Step 3: Validate licenses
            license_validation = self._validate_licenses(sbom_doc)

            if license_validation["blocked"]:
                if self.plugin_config.fail_on_blocked_licenses:
                    blocked_str = ", ".join(license_validation["blocked"])

                    raise PluginViolationError(
                        message=f"Blocked licenses detected: {blocked_str}",
                        violation=PluginViolation(
                            reason="Blocked licenses detected",
                            description=(f"Server contains blocked licenses: {blocked_str}. " f"Registration blocked by license policy."),
                            code="BLOCKED_LICENSE",
                            details={
                                "blocked_licenses": license_validation["blocked"],
                                "component_count": sbom_doc.component_count,
                            },
                        ),
                    )

            # Step 4: Store SBOM in database
            sbom_id = await self._store_sbom(context, server_id, sbom_doc)

            # Step 5: Return success
            logger.info(f"Successfully generated SBOM for server {server_id}: " f"{sbom_doc.component_count} components, " f"{len(sbom_doc.licenses)} unique licenses")

            return {
                "sbom_id": str(sbom_id),
                "component_count": sbom_doc.component_count,
                "format": sbom_doc.format.value,
                "licenses": {
                    "total": len(sbom_doc.licenses),
                    "blocked": license_validation["blocked"],
                    "flagged": license_validation["flagged"],
                },
            }

        except PluginViolationError:
            # Re-raise violations
            raise

        except ExtractionError as e:
            logger.error(f"Dependency extraction failed: {e}")
            if self.plugin_config.fail_on_missing_sbom:
                raise PluginViolationError(
                    message=f"Dependency extraction failed: {e.message}",
                    violation=PluginViolation(
                        reason="Extraction failed",
                        description=f"Dependency extraction failed: {e.message}",
                        code="EXTRACTION_FAILED",
                        details={"error_type": "extraction", **e.details},
                    ),
                )
            return {"error": "extraction_failed", "details": str(e)}

        except GenerationError as e:
            logger.error(f"SBOM generation failed: {e}")
            if self.plugin_config.fail_on_missing_sbom:
                raise PluginViolationError(
                    message=f"SBOM generation failed: {e.message}",
                    violation=PluginViolation(
                        reason="Generation failed",
                        description=f"SBOM generation failed: {e.message}",
                        code="GENERATION_FAILED",
                        details={"error_type": "generation", **e.details},
                    ),
                )
            return {"error": "generation_failed", "details": str(e)}

        except StorageError as e:
            logger.error(f"SBOM storage failed: {e}")
            raise PluginViolationError(
                message=f"SBOM storage failed: {e.message}",
                violation=PluginViolation(
                    reason="Storage failed",
                    description=f"SBOM storage failed: {e.message}",
                    code="STORAGE_FAILED",
                    details={"error_type": "storage", **e.details},
                ),
            )

        except SBOMGeneratorError as e:
            logger.error(f"SBOM generation error: {e}")
            if self.plugin_config.fail_on_missing_sbom:
                raise PluginViolationError(
                    message=str(e),
                    violation=PluginViolation(
                        reason="SBOM generation failed",
                        description=str(e),
                        code="SBOM_GENERATION_FAILED",
                        details={"error_type": "general", **e.details},
                    ),
                )
            return {"error": "sbom_generation_failed", "details": str(e)}

        except Exception as e:
            logger.exception(f"Unexpected error during SBOM generation: {e}")
            raise PluginViolationError(
                message=f"Unexpected error: {str(e)}",
                violation=PluginViolation(
                    reason="Unexpected error",
                    description=f"Unexpected error during SBOM generation: {str(e)}",
                    code="UNEXPECTED_ERROR",
                    details={"error_type": "unexpected"},
                ),
            )

    async def _extract_dependencies(self, context: PluginContext, payload: dict[str, Any]) -> ExtractionResult:
        """Extract dependencies using appropriate extractor.

        Determines target type from payload and selects the correct extractor
        (container vs source directory).

        Args:
            context: Plugin execution context
            payload: Assessment data with server metadata

        Returns:
            ExtractionResult with discovered components

        Raises:
            ExtractionError: If extraction fails
        """
        # Local
        from .extraction.container_extractor import ContainerExtractor
        from .extraction.source_extractor import SourceExtractor

        # Determine target from payload
        target = self._determine_target(payload)

        logger.debug(f"Extracting dependencies from target: {target}")

        # Select appropriate extractor
        extractors = [
            ContainerExtractor(
                fmt=self.plugin_config.syft.format,
                timeout=self.plugin_config.syft.timeout_seconds,
            ),
            SourceExtractor(
                fmt=self.plugin_config.syft.format,
                timeout=self.plugin_config.syft.timeout_seconds,
            ),
        ]

        for extractor in extractors:
            if extractor.supports(target):
                logger.debug(f"Using {extractor.__class__.__name__} for target: {target}")
                return await extractor.extract(target)

        raise ExtractionError(
            f"No extractor available for target: {target}",
            details={"target": target, "server_type": payload.get("server_type")},
        )

    def _determine_target(self, payload: dict[str, Any]) -> str:
        """Determine extraction target from assessment payload.

        Args:
            payload: Assessment data

        Returns:
            Target string for extraction (image name or directory path)
        """
        server_type = payload.get("server_type", "source")

        if server_type == "container":
            # Container image extraction
            image_name = payload.get("image_name")
            if not image_name:
                raise ValidationError("image_name required for container servers")
            return image_name

        else:
            # Source directory extraction
            source_path = payload.get("source_path")
            if not source_path:
                raise ValidationError("source_path required for source servers")
            # Syft expects dir:<path> format for directories
            return f"dir:{source_path}"

    async def _generate_sbom(
        self,
        context: PluginContext,
        extraction_result: ExtractionResult,
        payload: dict[str, Any],
    ) -> SBOMDocument:
        """Generate SBOM document from extraction result.

        Args:
            context: Plugin execution context
            extraction_result: Extracted components
            payload: Assessment data with server metadata

        Returns:
            Complete SBOMDocument

        Raises:
            GenerationError: If document generation fails
        """
        # Local
        from .generation.cyclonedx import CycloneDXGenerator
        from .generation.spdx import SPDXGenerator

        server_name = payload.get("server_name")
        server_version = payload.get("server_version")

        # Select generator based on configured format
        if self.plugin_config.syft.format == "cyclonedx":
            generator = CycloneDXGenerator(
                spec_version=self.plugin_config.syft.spec_version,
                tool_name="mcp-gateway-sbom-generator",
                tool_version=self.config.version or "0.1.0",
            )
        elif self.plugin_config.syft.format == "spdx":
            generator = SPDXGenerator(
                spec_version=self.plugin_config.syft.spec_version,
                tool_name="mcp-gateway-sbom-generator",
                tool_version=self.config.version or "0.1.0",
            )
        else:
            raise GenerationError(
                f"Unsupported SBOM format: {self.plugin_config.syft.format}",
                details={"format": self.plugin_config.syft.format},
            )

        logger.debug(f"Generating {self.plugin_config.syft.format.upper()} SBOM " f"for {server_name or 'unknown'}")

        return generator.generate(
            extraction_result=extraction_result,
            server_name=server_name,
            server_version=server_version,
        )

    def _validate_licenses(self, sbom_doc: SBOMDocument) -> dict[str, list[str]]:
        """Validate licenses against policy.

        Args:
            sbom_doc: SBOM document to validate

        Returns:
            Dict with 'blocked', 'flagged', and 'allowed' license lists
        """
        licenses = list(sbom_doc.licenses)
        validation_result = self.license_policy.validate_licenses(licenses)

        logger.debug(f"License validation: " f"{len(validation_result['blocked'])} blocked, " f"{len(validation_result['flagged'])} flagged, " f"{len(validation_result['allowed'])} allowed")

        return validation_result

    async def _store_sbom(self, context: PluginContext, server_id: str, sbom_doc: SBOMDocument) -> str:
        """Store SBOM in database.

        Args:
            context: Plugin execution context with DB session
            server_id: Server UUID
            sbom_doc: SBOM document to store

        Returns:
            SBOM document ID

        Raises:
            StorageError: If database operation fails
        """
        # Local
        from .storage import SBOMRepository

        session = context.db_session
        repository = SBOMRepository(session)

        db_sbom = repository.create_sbom(
            server_id=server_id,
            sbom_doc=sbom_doc,
            compress=self.plugin_config.storage.enable_compression,
        )

        logger.info(f"Stored SBOM in database: {db_sbom.id}")
        return db_sbom.id

    async def health_check(self) -> dict[str, Any]:
        """Check plugin health.

        Returns:
            Health status dict with plugin info
        """
        try:
            # Check if Syft is available
            # Local
            from .extraction.syft_wrapper import get_syft_version

            syft_version = await get_syft_version()

            return {
                "status": "healthy",
                "plugin": self.config.name,
                "version": self.config.version or "0.1.0",
                "config": {
                    "format": self.plugin_config.syft.format,
                    "generator": "syft",
                    "syft_version": syft_version,
                },
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "plugin": self.config.name,
                "error": str(e),
            }

    async def cleanup(self):
        """Cleanup plugin resources."""
        logger.info(f"Cleaning up {self.config.name} plugin")
        pass
