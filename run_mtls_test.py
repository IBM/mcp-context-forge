import os
import ssl
import uvicorn
import asyncio
from mcpgateway.translate import _PubSub, StdIOEndpoint, _build_fastapi

async def run_secure_server():
    print("🔐 Pornire MCP Translator cu mTLS (Port 9000)...")
    
    # 1. Inițializăm componentele interne (bazat pe logica din translate.py)
    pubsub = _PubSub()
    stdio_command = os.getenv("STDIO_COMMAND", "uvx mcp-server-time")
    stdio = StdIOEndpoint(stdio_command, pubsub)
    
    # Pornim procesul stdio (serverul de timp)
    await stdio.start()
    
    # 2. Construim aplicația FastAPI folosind factory-ul intern
    app = _build_fastapi(pubsub, stdio)
    
    # 3. Configurăm și pornim Uvicorn cu mTLS activat
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=9000,
        ssl_keyfile="/tmp/certs/server.key",
        ssl_certfile="/tmp/certs/server.crt",
        ssl_ca_certs="/tmp/certs/ca.crt",
        ssl_cert_reqs=ssl.CERT_REQUIRED, # Forțează mTLS
        log_level="info"
    )
    
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    try:
        asyncio.run(run_secure_server())
    except KeyboardInterrupt:
        pass