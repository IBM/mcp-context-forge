# -*- coding: utf-8 -*-
"""
Startup entry point for: python -m mcpgateway

Calls ensure_env_file_secrets() BEFORE importing mcpgateway.config so that
the pydantic-settings Settings singleton reads the freshly-generated values
from os.environ rather than the weak Field defaults.
"""


def main() -> None:
    """Ensure secrets are strong, then start the uvicorn server."""
    # IMPORTANT: import only stdlib here — mcpgateway.config must not be
    # imported until os.environ has been patched by ensure_env_file_secrets().
    # First-Party
    from mcpgateway.scripts.init_secrets import ensure_env_file_secrets  # noqa: PLC0415

    generated = ensure_env_file_secrets()
    if generated:
        keys = ", ".join(generated.keys())
        print(
            f"[startup] Auto-generated secrets for: {keys}. " "Written to .env. Subsequent starts will load these values without regeneration.",
            flush=True,
        )

    # Only import uvicorn and settings after os.environ is patched.
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
