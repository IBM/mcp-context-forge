# -*- coding: utf-8 -*-
"""Entry point for load testing module.

Allows running as: python -m tests.load.generate
"""

import sys

if len(sys.argv) > 1 and sys.argv[1] in ["generate", "cleanup", "verify"]:
    command = sys.argv.pop(1)

    if command == "generate":
        from .generate import main
    elif command == "cleanup":
        from .cleanup import main
    elif command == "verify":
        from .verify import main

    main()
else:
    print("Usage:")
    print("  python -m tests.load generate [options]")
    print("  python -m tests.load cleanup [options]")
    print("  python -m tests.load verify [options]")
    sys.exit(1)
