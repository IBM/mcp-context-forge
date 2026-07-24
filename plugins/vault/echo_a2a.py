# -*- coding: utf-8 -*-
"""Throwaway A2A echo server for Vault plugin E2E validation.

Runs a minimal FastAPI app that reflects the headers it received back in the JSON
response body. Point an A2A agent's endpoint_url at http://localhost:8002/invoke so
we can assert the gateway forwarded the vault-injected Authorization header and
stripped the X-Vault-Tokens header.

Run:
    python plugins/vault/echo_a2a.py
"""

# Third-Party
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()


@app.post("/invoke")
async def invoke(request: Request):
    """Reflect received headers (and body) so the caller can inspect them."""
    body = await request.body()
    received_headers = {k.lower(): v for k, v in request.headers.items()}
    # Also log to stdout for live observation
    print(f"[echo_a2a] received_headers={received_headers}")
    print(f"[echo_a2a] body={body.decode('utf-8', errors='replace')}")
    return JSONResponse(
        content={
            "ok": True,
            "received_headers": received_headers,
            "messages": [{"role": "assistant", "content": "echo"}],
        }
    )


@app.get("/health")
async def health():
    """Simple readiness probe."""
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
