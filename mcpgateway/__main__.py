# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/__main__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Startup entry point for: python -m mcpgateway
"""


def main() -> None:
    """Start the uvicorn server."""
    # Third-Party
    import uvicorn  # noqa: PLC0415

    # First-Party
    from mcpgateway.config import settings  # noqa: PLC0415

    uvicorn.run(
        "mcpgateway.main:app",
        host=str(settings.host),
        port=int(settings.port),
        reload=bool(settings.reload),
        log_level=str(settings.log_level).lower(),
    )


if __name__ == "__main__":
    main()
