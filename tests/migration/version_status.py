#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show current migration testing version configuration."""

from version_config import VersionConfig, get_supported_versions, get_migration_pairs


def main():
    print("=== MCP Gateway Migration Test Version Status ===")
    print()

    # Current configuration
    print("📊 Current Configuration (n-2 policy):")
    supported = get_supported_versions()
    all_versions = VersionConfig.get_all_versions()

    print(f"  Supported versions: {', '.join(supported)}")
    print(f"  All versions: {', '.join(all_versions)}")
    print(f"  Current version: {VersionConfig.CURRENT_VERSION}")
    print()

    # Version status breakdown
    print("📋 Version Status:")
    for version in all_versions:
        info = VersionConfig.get_version_info(version)
        status = info.get("support_status", "unknown")

        # Add emoji based on status
        if status == "current":
            emoji = "🟢"  # Current
        elif status == "supported":
            emoji = "🟡"  # Supported
        elif status == "legacy":
            emoji = "🔴"  # Legacy
        else:
            emoji = "⚪"  # Unknown

        supported_text = " (tested)" if VersionConfig.is_version_supported(version) else ""
        print(f"  {emoji} {version:<8} - {status}{supported_text}")

    print()

    # Migration pairs
    pairs = get_migration_pairs()

    print("🔄 Migration Test Pairs:")
    print("  Forward migrations:")
    for from_ver, to_ver in pairs["forward"]:
        print(f"    {from_ver} → {to_ver}")

    if pairs["reverse"]:
        print("  Reverse migrations:")
        for from_ver, to_ver in pairs["reverse"]:
            print(f"    {from_ver} ← {to_ver}")

    if pairs["skip"]:
        print("  Skip-version migrations:")
        for from_ver, to_ver in pairs["skip"]:
            print(f"    {from_ver} ⏭️  {to_ver}")

    print()

    # Container images
    print("🐳 Container Images:")
    for image in VersionConfig.get_container_images():
        print(f"  {image}")

    print()

    # Adding new version info
    print("➕ To add a new version (e.g., 0.7.0):")
    print("  1. Run: python3 add_version.py 0.7.0")
    print("  2. Follow the instructions")
    print("  3. Run: make migration-setup")


if __name__ == "__main__":
    main()
