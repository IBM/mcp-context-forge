# -*- coding: utf-8 -*-
"""Location: ./tests/migration/version_config.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Version configuration for migration testing.

This module defines the version configuration for migration testing,
following an n-2 support policy where we test the current version
and the two previous versions.
"""

# Standard
from datetime import datetime
from typing import Any, Dict, List, Tuple


class VersionConfig:
    """Configuration for migration testing versions.

    This class manages version information and generates test scenarios
    following the n-2 support policy. When adding a new version:

    1. Add it to RELEASES list
    2. Update CURRENT_VERSION
    3. The class automatically determines which versions to test
    """

    # All available releases in chronological order
    RELEASES = [
        "0.2.0",  # Legacy - not tested by default
        "0.3.0",  # Legacy - not tested by default
        "0.4.0",  # Legacy - not tested by default
        "0.5.0",  # n-2: Current support baseline
        "0.6.0",  # n-1: Previous version
        "latest",  # n:   Current development version
    ]

    # Current latest numbered version (update when releasing)
    CURRENT_VERSION = "0.6.0"

    # Release metadata for documentation and testing
    RELEASE_INFO = {
        "0.2.0": {"release_date": "2023-10-01", "major_features": ["basic_mcp_support", "sqlite_database", "simple_auth"], "breaking_changes": [], "support_status": "legacy"},
        "0.3.0": {
            "release_date": "2023-11-15",
            "major_features": ["display_names", "enhanced_annotations", "improved_validation"],
            "breaking_changes": ["annotation_schema_changes"],
            "support_status": "legacy",
        },
        "0.4.0": {
            "release_date": "2023-12-20",
            "major_features": ["uuid_primary_keys", "slug_system", "metadata_tracking"],
            "breaking_changes": ["primary_key_migration", "slug_introduction"],
            "support_status": "legacy",
        },
        "0.5.0": {
            "release_date": "2024-01-25",
            "major_features": ["enhanced_status", "improved_logging", "performance_optimizations"],
            "breaking_changes": ["status_field_changes"],
            "support_status": "supported",  # n-2
        },
        "0.6.0": {
            "release_date": "2024-02-15",
            "major_features": ["a2a_agents", "oauth_support", "federation_features"],
            "breaking_changes": ["oauth_table_addition"],
            "support_status": "supported",  # n-1
        },
        "latest": {
            "release_date": datetime.now().strftime("%Y-%m-%d"),
            "major_features": ["all_features", "latest_improvements", "cutting_edge"],
            "breaking_changes": ["potential_schema_updates"],
            "support_status": "current",  # n
        },
    }

    @classmethod
    def get_supported_versions(cls) -> List[str]:
        """Get versions that are currently supported (n-2 policy).

        Returns the last 3 versions: n-2, n-1, and latest.

        Returns:
            List of supported version strings
        """
        # Take the last 3 versions from RELEASES
        return cls.RELEASES[-3:]

    @classmethod
    def get_all_versions(cls) -> List[str]:
        """Get all available versions for comprehensive testing.

        Returns:
            List of all version strings
        """
        return cls.RELEASES.copy()

    @classmethod
    def get_forward_migration_pairs(cls) -> List[Tuple[str, str]]:
        """Generate version pairs for forward migration testing.

        Creates sequential pairs from supported versions:
        - n-2 → n-1
        - n-1 → n (latest)

        Returns:
            List of (from_version, to_version) tuples
        """
        supported = cls.get_supported_versions()
        pairs = []

        for i in range(len(supported) - 1):
            pairs.append((supported[i], supported[i + 1]))

        return pairs

    @classmethod
    def get_reverse_migration_pairs(cls) -> List[Tuple[str, str]]:
        """Generate version pairs for reverse migration testing.

        Creates reverse sequential pairs from supported versions:
        - n (latest) → n-1
        - n-1 → n-2

        Returns:
            List of (from_version, to_version) tuples
        """
        supported = cls.get_supported_versions()
        pairs = []

        for i in range(len(supported) - 1, 0, -1):
            pairs.append((supported[i], supported[i - 1]))

        return pairs

    @classmethod
    def get_skip_version_pairs(cls) -> List[Tuple[str, str]]:
        """Generate version pairs for skip-version migration testing.

        Creates pairs that skip intermediate versions:
        - n-2 → n (latest) [skips n-1]

        Returns:
            List of (from_version, to_version) tuples
        """
        supported = cls.get_supported_versions()

        if len(supported) >= 3:
            # Skip from n-2 directly to latest (n)
            return [(supported[0], supported[-1])]
        else:
            return []

    @classmethod
    def get_version_info(cls, version: str) -> Dict[str, Any]:
        """Get metadata for a specific version.

        Args:
            version: Version string to get info for

        Returns:
            Dictionary containing version metadata
        """
        return cls.RELEASE_INFO.get(version, {})

    @classmethod
    def is_version_supported(cls, version: str) -> bool:
        """Check if a version is currently supported.

        Args:
            version: Version string to check

        Returns:
            True if version is in supported list
        """
        return version in cls.get_supported_versions()

    @classmethod
    def get_container_images(cls, include_all: bool = False) -> List[str]:
        """Get container image names for testing.

        Args:
            include_all: If True, return all versions; if False, only supported

        Returns:
            List of container image names
        """
        versions = cls.get_all_versions() if include_all else cls.get_supported_versions()
        return [f"ghcr.io/ibm/mcp-context-forge:{version}" for version in versions]

    @classmethod
    def add_new_version(cls, version: str, info: Dict[str, Any]) -> None:
        """Helper method to add a new version (for future use).

        This method documents how to add a new version:

        1. Add version to RELEASES list
        2. Update CURRENT_VERSION if it's the new latest numbered version
        3. Add entry to RELEASE_INFO
        4. The n-2 policy will automatically adjust

        Args:
            version: New version string (e.g., "0.7.0")
            info: Version metadata dictionary
        """
        raise NotImplementedError(
            "To add a new version:\n"
            "1. Add version to VersionConfig.RELEASES list\n"
            "2. Update VersionConfig.CURRENT_VERSION if needed\n"
            "3. Add entry to VersionConfig.RELEASE_INFO\n"
            "4. Update test data files in fixtures/test_data_sets/\n"
            "5. Run 'make migration-setup' to pull new images"
        )


# Convenience functions for direct import
def get_supported_versions() -> List[str]:
    """Get currently supported versions (n-2 policy)."""
    return VersionConfig.get_supported_versions()


def get_migration_pairs() -> Dict[str, List[Tuple[str, str]]]:
    """Get all migration test pairs organized by type."""
    return {"forward": VersionConfig.get_forward_migration_pairs(), "reverse": VersionConfig.get_reverse_migration_pairs(), "skip": VersionConfig.get_skip_version_pairs()}


# Example usage and documentation
if __name__ == "__main__":
    print("=== MCP Gateway Migration Test Version Configuration ===")
    print(f"Supported versions (n-2 policy): {get_supported_versions()}")
    print(f"All versions: {VersionConfig.get_all_versions()}")
    print()

    pairs = get_migration_pairs()
    print("Forward migration pairs:")
    for pair in pairs["forward"]:
        print(f"  {pair[0]} → {pair[1]}")
    print()

    print("Reverse migration pairs:")
    for pair in pairs["reverse"]:
        print(f"  {pair[0]} → {pair[1]}")
    print()

    print("Skip-version migration pairs:")
    for pair in pairs["skip"]:
        print(f"  {pair[0]} ⏭️  {pair[1]}")
    print()

    print("Container images:")
    for image in VersionConfig.get_container_images():
        print(f"  {image}")
