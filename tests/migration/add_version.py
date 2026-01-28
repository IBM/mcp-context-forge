#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/migration/add_version.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Helper script to add a new version to migration testing.

This script demonstrates how to add a new version like 0.7.0 to the
migration test suite. It shows exactly what needs to be updated.

Usage:
    python3 tests/migration/add_version.py 0.7.0
"""

# Standard
from datetime import datetime
import json
from pathlib import Path
import sys


def show_instructions(new_version: str):
    """Show step-by-step instructions for adding a new version."""

    print(f"=== Adding Migration Test Support for Version {new_version} ===")
    print()

    print("📋 Steps to add a new version:")
    print()

    print("1. Update version_config.py:")
    print(f"   - Add '{new_version}' to RELEASES list")
    print(f"   - Update CURRENT_VERSION to '{new_version}' if it's the new latest")
    print("   - Add entry to RELEASE_INFO with metadata")
    print()

    print("2. Create test data file:")
    test_data_file = f"fixtures/test_data_sets/v{new_version.replace('.', '_')}_sample.json"
    print(f"   - Create {test_data_file}")
    print("   - Base it on latest_sample.json structure")
    print()

    print("3. Update container images:")
    print(f"   - Ensure ghcr.io/ibm/mcp-context-forge:{new_version} exists")
    print("   - Run 'make migration-setup' to pull new images")
    print()

    print("4. The migration tests will automatically:")
    print("   - Include the new version in n-2 policy")
    print("   - Generate appropriate test pairs")
    print("   - Update Makefile version list")
    print()

    print("🔧 Example version_config.py updates:")
    print()
    print("RELEASES = [")
    print('    "0.2.0",  # Legacy')
    print('    "0.3.0",  # Legacy')
    print('    "0.4.0",  # Legacy')
    print('    "0.5.0",  # Legacy (was n-2)')
    print('    "0.6.0",  # n-2')
    print(f'    "{new_version}",  # n-1')
    print('    "latest", # n')
    print("]")
    print()
    print(f'CURRENT_VERSION = "{new_version}"')
    print()
    print("RELEASE_INFO = {")
    print("    # ... existing entries ...")
    print(f'    "{new_version}": {{')
    print(f'        "release_date": "{datetime.now().strftime("%Y-%m-%d")}",')
    print('        "major_features": ["new_feature_1", "new_feature_2"],')
    print('        "breaking_changes": ["breaking_change_if_any"],')
    print('        "support_status": "supported"  # n-1')
    print("    },")
    print("}")
    print()


def create_sample_test_data(new_version: str, output_path: Path):
    """Create a sample test data file for the new version."""

    # Load latest sample as template
    latest_file = output_path.parent / "latest_sample.json"
    if not latest_file.exists():
        print(f"❌ Template file not found: {latest_file}")
        return

    with open(latest_file, "r") as f:
        template_data = json.load(f)

    # Update metadata for new version
    template_data["metadata"]["version"] = new_version
    template_data["metadata"]["description"] = f"Sample test data for MCP Gateway v{new_version} migration testing"

    # Update annotations in test data to reflect new version
    for category in ["tools", "servers", "gateways", "resources", "prompts", "a2a_agents"]:
        if category in template_data.get("data", {}):
            for item in template_data["data"][category]:
                if "annotations" in item:
                    item["annotations"]["version"] = new_version

    # Write new test data file
    with open(output_path, "w") as f:
        json.dump(template_data, f, indent=2)

    print(f"✅ Created sample test data: {output_path}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 add_version.py <new_version>")
        print("Example: python3 add_version.py 0.7.0")
        sys.exit(1)

    new_version = sys.argv[1]

    # Validate version format
    if not new_version.replace(".", "").isdigit():
        print(f"❌ Invalid version format: {new_version}")
        print("Expected format: x.y.z (e.g., 0.7.0)")
        sys.exit(1)

    # Show instructions
    show_instructions(new_version)

    # Offer to create sample test data
    response = input(f"\n📝 Create sample test data file for {new_version}? (y/n): ")
    if response.lower().startswith("y"):
        script_dir = Path(__file__).parent
        test_data_file = script_dir / "fixtures" / "test_data_sets" / f"v{new_version.replace('.', '_')}_sample.json"
        test_data_file.parent.mkdir(parents=True, exist_ok=True)

        create_sample_test_data(new_version, test_data_file)

    print()
    print("🎉 Next steps:")
    print("1. Make the changes shown above")
    print("2. Test the configuration:")
    print("   python3 -c 'from version_config import VersionConfig; print(VersionConfig.get_supported_versions())'")
    print("3. Run migration setup:")
    print("   make migration-setup")
    print("4. Run migration tests:")
    print("   make test-migration-sqlite")


if __name__ == "__main__":
    main()
