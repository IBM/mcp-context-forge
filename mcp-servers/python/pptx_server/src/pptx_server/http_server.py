# -*- coding: utf-8 -*-
"""Location: ./mcp-servers/python/pptx_server/src/pptx_server/http_server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

HTTP file serving for PowerPoint MCP Server downloads.
"""

# Standard
import os
from datetime import datetime
from typing import Any

import uvicorn

# Third-Party
import orjson

# Third-Party
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Local
from .server import config

# Ensure config directories exist
config.ensure_directories()


app = FastAPI(
    title="PowerPoint MCP Server Downloads",
    description="Secure file download service for PowerPoint presentations",
    version="0.1.0",
)


@app.get("/")
async def root():
    """Root endpoint with server information."""
    return {
        "server": "PowerPoint MCP Server - Download Service",
        "version": "0.1.0",
        "status": "running",
        "download_endpoint": "/download/{token}/{filename}",
        "health_endpoint": "/health",
    }


def _load_token_info(token: str) -> dict[str, Any] | None:
    """Load token info from file storage."""
    tokens_dir = os.path.join(config.work_dir, "tokens")
    token_file = os.path.join(tokens_dir, f"{token}.json")

    if not os.path.exists(token_file):
        return None

    try:
        with open(token_file, "rb") as f:
            token_info = orjson.loads(f.read())

        # Check if token has expired
        expires = datetime.fromisoformat(token_info["expires"])
        if datetime.now() > expires:
            # Remove expired token file
            os.remove(token_file)
            return None

        return token_info
    except Exception:
        return None


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    # Count active token files
    tokens_dir = os.path.join(config.work_dir, "tokens")
    active_tokens = 0
    if os.path.exists(tokens_dir):
        active_tokens = len([f for f in os.listdir(tokens_dir) if f.endswith(".json")])

    return {
        "status": "healthy",
        "active_download_tokens": active_tokens,
        "work_directory": config.work_dir,
        "downloads_enabled": config.enable_downloads,
    }


@app.get("/download/{token}/{filename}")
async def download_file(token: str, filename: str):
    """Download a file using a secure token."""
    # Load token info from file storage
    token_info = _load_token_info(token)
    if token_info is None:
        raise HTTPException(status_code=404, detail="Download token not found or expired")

    file_path = token_info["file_path"]

    # Verify file still exists
    if not os.path.exists(file_path):
        # Clean up invalid token
        del _download_tokens[token]
        raise HTTPException(status_code=404, detail="File not found")

    # Validate file is still in allowed directory (security check)
    abs_path = os.path.abspath(file_path)
    allowed_dirs = [
        os.path.abspath(config.output_dir),
        os.path.abspath(config.temp_dir),
        os.path.abspath(os.path.join(config.work_dir, "sessions")),
        os.path.abspath("examples/generated"),
        os.path.abspath("examples/demos"),
    ]

    is_allowed = any(abs_path.startswith(allowed_dir) for allowed_dir in allowed_dirs)
    if not is_allowed:
        raise HTTPException(status_code=403, detail="File access denied")

    # Get file info
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    # Return file for download
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Session-ID": token_info["session_id"],
            "X-File-Size": str(file_size),
            "X-Token-Expires": token_info["expires"].isoformat(),
        },
    )


@app.get("/tokens")
async def list_active_tokens():
    """List active download tokens (for debugging)."""
    if not config.server_debug:
        raise HTTPException(status_code=403, detail="Debug endpoint disabled")

    tokens = []
    tokens_dir = os.path.join(config.work_dir, "tokens")

    if os.path.exists(tokens_dir):
        for token_file in os.listdir(tokens_dir):
            if token_file.endswith(".json"):
                token = token_file[:-5]  # Remove .json extension
                token_info = _load_token_info(token)
                if token_info:
                    tokens.append(
                        {
                            "token": token[:16] + "...",  # Partial token for security
                            "filename": os.path.basename(token_info["file_path"]),
                            "session_id": token_info["session_id"][:8] + "...",
                            "expires": token_info["expires"],
                            "created": token_info["created"],
                        }
                    )

    return {"active_tokens": len(tokens), "tokens": tokens}


def start_download_server(host: str = None, port: int = None):
    """Start the HTTP download server."""
    server_host = host or config.server_host
    server_port = port or config.server_port

    print("🌐 Starting PowerPoint MCP Download Server...")
    print(f"📥 Download endpoint: http://{server_host}:{server_port}/download/{{token}}")
    print(f"❤️  Health check: http://{server_host}:{server_port}/health")

    uvicorn.run(
        app,
        host=server_host,
        port=server_port,
        log_level="info" if config.server_debug else "warning",
    )


if __name__ == "__main__":
    start_download_server()
