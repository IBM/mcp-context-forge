#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration Tests Setup Verification

Location: tests/integration/test_source_scanners/verify_setup.py
Copyright 2026
Authors: Yaser
Verify that all requirements are met to run integration tests.
"""

#!/usr/bin/env python3

# Standard
from pathlib import Path
import subprocess
import sys


def run_command(cmd: list[str]) -> tuple[bool, str, str]:
    """Run command and return success, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)


def check_command(cmd: str, version_cmd: list[str] = None) -> tuple[bool, str]:
    """Check if command is available and get version."""
    success, stdout, _ = run_command([cmd, "--version"] if not version_cmd else version_cmd)
    if success:
        version_line = stdout.strip().split("\n")[0]
        return True, version_line
    return False, ""


def check_python_package(package: str) -> tuple[bool, str]:
    """Check if Python package is installed and get version."""
    try:
        mod = __import__(package)
        version = getattr(mod, "__version__", "unknown")
        return True, f"{package} {version}"
    except ImportError:
        return False, ""


def main() -> int:
    """Run all verification checks."""
    print("=" * 60)
    print("Integration Tests Setup Verification")
    print("=" * 60)
    print()

    all_ok = True

    # Check Python version
    print("🔍 Checking Python version...")
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        print(f"   ✅ Python {py_version} (3.11+ required)")
    else:
        print(f"   ❌ Python {py_version} (3.11+ required)")
        all_ok = False
    print()

    # Check system commands
    print("🔍 Checking system commands...")

    for cmd in ["git", "semgrep", "bandit"]:
        available, version = check_command(cmd)
        if available:
            print(f"   ✅ {cmd:12} {version}")
        else:
            print(f"   ❌ {cmd:12} NOT FOUND")
            all_ok = False
    print()

    # Check Python packages
    print("🔍 Checking Python packages...")

    required_packages = {
        "pytest": "testing",
        "pytest_asyncio": "async testing",
        "mcpgateway": "main gateway",
        "plugins": "plugin framework",
    }

    for package, desc in required_packages.items():
        available, version = check_python_package(package)
        if available:
            print(f"   ✅ {package:20} {version:30} ({desc})")
        else:
            print(f"   ❌ {package:20} NOT FOUND ({desc})")
            all_ok = False
    print()

    # Check test files
    print("🔍 Checking test files...")

    test_files = [
        "conftest.py",
        "test_real_repo_scan.py",
        "test_bandit_integration.py",
        "test_semgrep_integration.py",
        "pytest.ini",
        "run_integration_tests.sh",
    ]

    test_dir = Path(__file__).parent
    for test_file in test_files:
        file_path = test_dir / test_file
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"   ✅ {test_file:35} ({size:6} bytes)")
        else:
            print(f"   ❌ {test_file:35} NOT FOUND")
            all_ok = False
    print()

    # Check documentation
    print("🔍 Checking documentation...")

    docs = [
        "README.md",
        "QUICKSTART.md",
        "INTEGRATION_TEST_SUMMARY.md",
        "INDEX.md",
    ]

    for doc_file in docs:
        file_path = test_dir / doc_file
        if file_path.exists():
            size = file_path.stat().st_size
            print(f"   ✅ {doc_file:35} ({size:6} bytes)")
        else:
            print(f"   ⚠️  {doc_file:35} NOT FOUND (optional)")
    print()

    # Summary
    print("=" * 60)
    if all_ok:
        print("✅ All checks passed! Ready to run integration tests.")
        print()
        print("Next steps:")
        print("  1. Run all tests:")
        print("     pytest tests/integration/test_source_scanners/ -v -m integration")
        print()
        print("  2. Or use the convenience script:")
        print("     bash tests/integration/test_source_scanners/run_integration_tests.sh all")
        print()
        print("  3. Or start with a quick test:")
        print("     pytest tests/integration/test_source_scanners/test_real_repo_scan.py::TestWebGoatRepoScan::test_webgoat_full_scan -v -s")
        print()
        return 0

    print("❌ Some checks failed. Please install missing dependencies.")
    print()
    print("Install missing tools:")
    print("  System: sudo apt-get install git semgrep bandit")
    print("  Or pip: pip install semgrep bandit")
    print()
    print("Install missing Python packages:")
    print("  make install-dev")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
