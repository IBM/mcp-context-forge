#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security configuration checker for ContextForge."""

import sys
import os

# Add the project root to the path (two levels up from .github/tools/)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from mcpgateway.config import get_settings


def main():
    """Check security configuration and exit with appropriate code."""
    try:
        settings = get_settings()
        status = settings.get_security_status()

        print(f"Security Score: {status['security_score']}/100")
        print(f"Warnings: {len(status['warnings'])}")

        if status["warnings"]:
            print("\nSecurity Warnings:")
            for warning in status["warnings"]:
                print(f"  - {warning}")

        # Exit with error if score is too low
        if status["security_score"] < 60:
            print("\n❌ Security score too low for deployment")
            sys.exit(1)
        elif status["security_score"] < 80:
            print("\n⚠️  Security could be improved")
            sys.exit(0)
        else:
            print("\n✅ Security configuration looks good")
            sys.exit(0)

    except Exception as e:
        print(f"❌ Security validation failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
