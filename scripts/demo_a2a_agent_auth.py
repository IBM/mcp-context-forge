#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo A2A Agent with Authentication for Issue #2002 Testing.

This script creates a simple A2A agent that supports multiple authentication methods:
- Basic Auth (username/password)
- Bearer Token
- X-API-Key header

Based on sample code from:
- Issue #840 demo_a2a_agent.py
- Issue #2002 gist: https://gist.github.com/jackic23/5d93092a657baf3e88f980f2d3d4352c
"""

import argparse
import ast
import atexit
import logging
import operator
import random
import secrets
import signal
import socket
import sys
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
import jwt
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# ============================================================================
# Configuration (set by command line arguments)
# ============================================================================

AUTH_TYPE = "none"
AUTH_USERNAME = "admin"
AUTH_PASSWORD = "password"
AUTH_TOKEN = "secret-bearer-token"
AUTH_API_KEY = "secret-api-key"
PORT = 0
CONTEXTFORGE_URL = "http://localhost:8000"
JWT_SECRET = "my-test-key"
AUTO_REGISTER = False
AGENT_NAME = ""

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="demo_a2a_agent_auth",
        description="""
Demo A2A Agent with Authentication for Issue #2002 Testing.

This script creates a simple A2A agent that supports multiple authentication
methods for testing the MCPGateway A2A authentication fix.

Supported tools:
  - calc: <expr>     Evaluate a math expression (e.g., "calc: 5*10+2")
  - weather: <city>  Get mock weather for a city (e.g., "weather: Dallas")
  - echo: <msg>      Echo back a message (e.g., "echo: Hello World")
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # No authentication (default)
  %(prog)s

  # Basic Auth
  %(prog)s --auth-type basic --username myuser --password mypass

  # Bearer Token
  %(prog)s --auth-type bearer --token my-secret-token

  # X-API-Key
  %(prog)s --auth-type apikey --api-key my-api-key

  # Specify port
  %(prog)s --port 9000 --auth-type basic --username admin --password secret

  # Auto-register with ContextForge
  %(prog)s --auth-type basic --username admin --password secret --auto-register

  # Auto-register with custom agent name
  %(prog)s --auth-type basic --auto-register --name my-custom-agent

ContextForge Registration:
  When registering this agent with ContextForge, use the following auth_type mappings:
    --auth-type basic   -> auth_type: basic, auth_username, auth_password
    --auth-type bearer  -> auth_type: bearer, auth_token
    --auth-type apikey  -> auth_type: authheaders, auth_headers: [{"key": "X-API-Key", "value": "<key>"}]
        """,
    )

    # Authentication options
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--auth-type",
        choices=["none", "basic", "bearer", "apikey"],
        default="none",
        help="Authentication type (default: none)",
    )
    auth_group.add_argument(
        "--username",
        default=None,
        help="Username for Basic Auth (default: admin)",
    )
    auth_group.add_argument(
        "--password",
        default=None,
        help="Password for Basic Auth (auto-generated if not provided)",
    )
    auth_group.add_argument(
        "--token",
        default=None,
        help="Token for Bearer Auth (auto-generated if not provided)",
    )
    auth_group.add_argument(
        "--api-key",
        default=None,
        help="API key for X-API-Key Auth (auto-generated if not provided)",
    )

    # Server options
    server_group = parser.add_argument_group("Server")
    server_group.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (default: auto-select available port)",
    )
    server_group.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )

    # ContextForge registration options
    cf_group = parser.add_argument_group("ContextForge Registration")
    cf_group.add_argument(
        "--auto-register",
        action="store_true",
        help="Auto-register with ContextForge on startup",
    )
    cf_group.add_argument(
        "--name",
        default=None,
        help="Agent name for registration (default: demo-a2a-auth-{auth_type}-{unique_suffix})",
    )
    cf_group.add_argument(
        "--contextforge-url",
        default="http://localhost:8000",
        help="ContextForge URL (default: http://localhost:8000)",
    )
    cf_group.add_argument(
        "--jwt-secret",
        default="my-test-key",
        help="JWT secret for ContextForge auth (default: my-test-key)",
    )

    return parser.parse_args()


# ============================================================================
# Security Dependencies
# ============================================================================

# Security schemes
basic_auth = HTTPBasic(auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_auth(
    request: Request,
    basic_credentials: HTTPBasicCredentials = Depends(basic_auth),
    bearer_credentials: HTTPAuthorizationCredentials = Security(bearer_auth),
    api_key: str = Security(api_key_header),
) -> str:
    """Verify authentication based on configured AUTH_TYPE.

    Returns the authenticated identity or raises HTTPException.
    """
    if AUTH_TYPE == "none":
        return "anonymous"

    if AUTH_TYPE == "basic":
        if basic_credentials:
            if secrets.compare_digest(basic_credentials.username, AUTH_USERNAME) and secrets.compare_digest(basic_credentials.password, AUTH_PASSWORD):
                logger.info(f"Basic Auth successful for user: {basic_credentials.username}")
                return basic_credentials.username
        logger.warning("Basic Auth failed - invalid or missing credentials")
        raise HTTPException(
            status_code=401,
            detail="Invalid Basic Auth credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if AUTH_TYPE == "bearer":
        if bearer_credentials:
            if secrets.compare_digest(bearer_credentials.credentials, AUTH_TOKEN):
                logger.info("Bearer Token authentication successful")
                return "bearer-authenticated"
        logger.warning("Bearer Token auth failed - invalid or missing token")
        raise HTTPException(
            status_code=401,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if AUTH_TYPE == "apikey":
        if api_key:
            if secrets.compare_digest(api_key, AUTH_API_KEY):
                logger.info("X-API-Key authentication successful")
                return "apikey-authenticated"
        logger.warning("X-API-Key auth failed - invalid or missing key")
        raise HTTPException(
            status_code=401,
            detail="Invalid X-API-Key",
        )

    # Unknown auth type - allow through with warning
    logger.warning(f"Unknown AUTH_TYPE: {AUTH_TYPE}, allowing request")
    return "unknown-auth"


# ============================================================================
# Tools Implementation
# ============================================================================


def calculator(expression: str) -> str:
    """Evaluate a math expression safely using ast module."""
    operators_map = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def safe_eval(node):
        """Recursively evaluate an AST node safely."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Invalid constant type: {type(node.value)}")
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in operators_map:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            left = safe_eval(node.left)
            right = safe_eval(node.right)
            return operators_map[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in operators_map:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            operand = safe_eval(node.operand)
            return operators_map[type(node.op)](operand)
        elif isinstance(node, ast.Expression):
            return safe_eval(node.body)
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = safe_eval(tree)
        return str(result)
    except (SyntaxError, ValueError) as e:
        return f"Error: {e}"
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error: {e}"


def weather(city: str) -> str:
    """Mock weather lookup tool."""
    conditions = ["sunny", "rainy", "cloudy", "stormy", "partly cloudy"]
    temp = random.randint(10, 35)
    return f"The weather in {city} is {random.choice(conditions)}, {temp}C"


def echo(message: str) -> str:
    """Echo back the message."""
    return f"Echo: {message}"


class SimpleAgent:
    """Simple A2A agent that routes queries to tools."""

    def __init__(self, name: str = "AuthDemo-Agent"):
        self.name = name
        self.tools = {
            "calculator": calculator,
            "weather": weather,
            "echo": echo,
        }

    def run(self, query: str) -> str:
        """Process a query and route to appropriate tool."""
        query_lower = query.lower()
        if "calc:" in query_lower:
            expr = query.split(":", 1)[1].strip()
            return self.tools["calculator"](expr)
        elif "weather:" in query_lower:
            city = query.split(":", 1)[1].strip()
            return self.tools["weather"](city.title())
        elif "echo:" in query_lower:
            msg = query.split(":", 1)[1].strip()
            return self.tools["echo"](msg)
        else:
            return f"{self.name} received: {query}. Try 'calc: 5*10', 'weather: Dallas', or 'echo: Hello'"


# ============================================================================
# Pydantic Models
# ============================================================================


class Parameters(BaseModel):
    """Parameters object containing the actual query."""

    query: str = ""
    message: str = ""


class A2ARequest(BaseModel):
    """Request model for A2A protocol format (ContextForge custom agent format)."""

    interaction_type: str = ""
    parameters: Optional[Parameters] = None
    protocol_version: str = ""
    # Also support direct query/message for simple testing
    query: str = ""
    message: str = ""


class MessagePart(BaseModel):
    """A2A message part."""

    kind: str = "text"
    text: str = ""


class AgentMessage(BaseModel):
    """A2A Message format (Google A2A protocol)."""

    messageId: str = ""
    role: str = "user"
    parts: list = []
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    metadata: Dict[str, Any] = {}


class Response(BaseModel):
    """Response model for agent results."""

    response: str
    status: str = "success"
    auth_type: str = AUTH_TYPE
    timestamp: str = ""


# ============================================================================
# FastAPI Application
# ============================================================================

agent = SimpleAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI."""
    logger.info("=" * 60)
    logger.info("Demo A2A Agent with Authentication (Issue #2002)")
    logger.info("=" * 60)
    logger.info(f"Auth Type: {AUTH_TYPE}")
    if AUTH_TYPE == "basic":
        logger.info(f"  Username: {AUTH_USERNAME}")
        logger.info(f"  Password: {'*' * len(AUTH_PASSWORD)}")
    elif AUTH_TYPE == "bearer":
        logger.info(f"  Token: {AUTH_TOKEN[:8]}...")
    elif AUTH_TYPE == "apikey":
        logger.info(f"  API Key: {AUTH_API_KEY[:8]}...")
    yield
    logger.info("Demo A2A Agent shutdown complete")


app = FastAPI(
    title="Demo A2A Agent with Auth",
    description="A2A Agent demonstrating Basic Auth, Bearer Token, and X-API-Key authentication (Issue #2002)",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root(identity: str = Depends(verify_auth)):
    """Root endpoint - returns server info."""
    return {
        "name": "Demo A2A Agent with Auth",
        "status": "running",
        "version": "1.0.0",
        "auth_type": AUTH_TYPE,
        "authenticated_as": identity,
        "endpoints": {
            "run": "/run",
            "message_send": "/message/send",
            "health": "/health",
            "agent_card": "/.well-known/agent-card.json",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint (no auth required)."""
    return {"status": "healthy", "agent": agent.name, "auth_type": AUTH_TYPE}


@app.get("/.well-known/agent-card.json")
async def get_agent_card(request: Request, identity: str = Depends(verify_auth)):
    """A2A Discovery endpoint - returns agent capabilities."""
    scheme = request.url.scheme
    host = request.headers.get("host", "localhost")
    base_url = f"{scheme}://{host}"

    return {
        "name": "Demo A2A Agent with Auth",
        "description": "Demo agent for testing A2A authentication (Issue #2002)",
        "version": "1.0.0",
        "url": base_url,
        "auth_type": AUTH_TYPE,
        "capabilities": [
            {
                "id": "calculator",
                "name": "Calculator",
                "description": "Evaluate math expressions (e.g., 'calc: 5*10+2')",
            },
            {
                "id": "weather",
                "name": "Weather",
                "description": "Get mock weather for a city (e.g., 'weather: Dallas')",
            },
            {
                "id": "echo",
                "name": "Echo",
                "description": "Echo back a message (e.g., 'echo: Hello')",
            },
        ],
    }


@app.post("/run")
async def run_agent(req: A2ARequest, identity: str = Depends(verify_auth)) -> Response:
    """Execute a query against the agent (ContextForge custom agent format).

    Supports both:
    - A2A protocol format: {"parameters": {"query": "..."}}
    - Simple format: {"query": "..."}
    """
    # Extract query from A2A protocol format or direct fields
    query_text = ""
    if req.parameters:
        query_text = req.parameters.query or req.parameters.message
    if not query_text:
        query_text = req.query or req.message or "Hello"

    logger.info(f"Processing query: {query_text[:50]}... (auth: {identity})")
    response_text = agent.run(query_text)

    return Response(
        response=response_text,
        status="success",
        auth_type=AUTH_TYPE,
        timestamp=datetime.now().isoformat(),
    )


@app.post("/message/send")
async def message_send(message: AgentMessage, identity: str = Depends(verify_auth)):
    """A2A Message endpoint (Google A2A protocol format)."""
    request_start = datetime.now()
    logger.info(f"POST /message/send - messageId: {message.messageId} (auth: {identity})")

    # Extract text from message parts
    text_parts = [part.get("text", "") for part in message.parts if isinstance(part, dict) and part.get("kind") == "text"]
    query = " ".join(text_parts)

    if not query:
        query = "Hello"

    response_text = agent.run(query)
    elapsed = (datetime.now() - request_start).total_seconds()

    return {
        "messageId": f"{message.messageId}_response",
        "role": "agent",
        "parts": [{"kind": "text", "text": response_text}],
        "metadata": {
            "processing_time": elapsed,
            "timestamp": datetime.now().isoformat(),
            "auth_type": AUTH_TYPE,
            "authenticated_as": identity,
        },
    }


# ============================================================================
# ContextForge Registration (Optional)
# ============================================================================

AGENT_ID = None


def create_jwt_token(username: str = "admin@example.com") -> str:
    """Create a JWT token for ContextForge authentication."""
    payload = {
        "sub": username,
        "email": username,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "teams": [],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def register_agent(port: int) -> str | None:
    """Register the A2A agent with ContextForge."""
    global AGENT_ID

    token = create_jwt_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # Build auth configuration based on AUTH_TYPE
    agent_data = {
        "agent": {
            "name": AGENT_NAME,
            "description": f"Demo A2A Agent with {AUTH_TYPE} authentication (Issue #2002)",
            "endpoint_url": f"http://localhost:{port}/run",
            "agent_type": "custom",
            "protocol_version": "1.0",
            "capabilities": {"tools": ["calculator", "weather", "echo"]},
            "config": {},
            "tags": ["demo", "auth", "issue-2002", AUTH_TYPE],
        },
        "visibility": "public",
    }

    # Add auth configuration
    if AUTH_TYPE == "basic":
        agent_data["agent"]["auth_type"] = "basic"
        agent_data["agent"]["auth_username"] = AUTH_USERNAME
        agent_data["agent"]["auth_password"] = AUTH_PASSWORD
    elif AUTH_TYPE == "bearer":
        agent_data["agent"]["auth_type"] = "bearer"
        agent_data["agent"]["auth_token"] = AUTH_TOKEN
    elif AUTH_TYPE == "apikey":
        agent_data["agent"]["auth_type"] = "authheaders"
        agent_data["agent"]["auth_headers"] = [{"key": "X-API-Key", "value": AUTH_API_KEY}]

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(f"{CONTEXTFORGE_URL}/a2a", headers=headers, json=agent_data)

            if response.status_code == 201:
                data = response.json()
                AGENT_ID = data.get("id")
                logger.info(f"Registered A2A agent with ContextForge: {AGENT_ID}")
                logger.info(f"  Name: {data.get('name')}")
                logger.info(f"  Endpoint: {data.get('endpointUrl')}")
                logger.info(f"  Auth Type: {AUTH_TYPE}")
                return AGENT_ID
            else:
                logger.error(f"Failed to register agent: {response.status_code}")
                logger.error(f"  Response: {response.text}")
                return None
    except Exception as e:
        logger.error(f"Error registering agent: {e}")
        return None


def unregister_agent():
    """Unregister the A2A agent from ContextForge."""
    if not AGENT_ID:
        return

    token = create_jwt_token()
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with httpx.Client(timeout=10) as client:
            response = client.delete(f"{CONTEXTFORGE_URL}/a2a/{AGENT_ID}", headers=headers)
            if response.status_code in (200, 204):
                logger.info(f"Unregistered A2A agent: {AGENT_ID}")
            else:
                logger.warning(f"Failed to unregister agent: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error unregistering agent: {e}")


def find_available_port(start: int = 9000, end: int = 9100) -> int:
    """Find an available port in the given range."""
    for port in range(start, end):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            if sock.connect_ex(("localhost", port)) != 0:
                return port
    raise RuntimeError(f"No available port found in range {start}-{end}")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    """Run the demo A2A agent with authentication."""
    global AUTH_TYPE, AUTH_USERNAME, AUTH_PASSWORD, AUTH_TOKEN, AUTH_API_KEY
    global PORT, CONTEXTFORGE_URL, JWT_SECRET, AUTO_REGISTER, AGENT_NAME

    # Parse command line arguments
    args = parse_args()

    # Set global configuration from arguments
    AUTH_TYPE = args.auth_type
    PORT = args.port
    CONTEXTFORGE_URL = args.contextforge_url
    JWT_SECRET = args.jwt_secret
    AUTO_REGISTER = args.auto_register
    host = args.host

    # Set agent name with unique suffix to avoid collisions
    if args.name:
        AGENT_NAME = args.name
    else:
        unique_suffix = secrets.token_hex(4)
        AGENT_NAME = f"demo-a2a-auth-{AUTH_TYPE}-{unique_suffix}"

    # Generate or use provided credentials based on auth type
    generated = []

    if AUTH_TYPE == "basic":
        AUTH_USERNAME = args.username if args.username else "admin"
        if args.password:
            AUTH_PASSWORD = args.password
        else:
            AUTH_PASSWORD = secrets.token_urlsafe(16)
            generated.append("password")
    else:
        AUTH_USERNAME = args.username if args.username else "admin"
        AUTH_PASSWORD = args.password if args.password else "password"

    if AUTH_TYPE == "bearer":
        if args.token:
            AUTH_TOKEN = args.token
        else:
            AUTH_TOKEN = secrets.token_urlsafe(32)
            generated.append("token")
    else:
        AUTH_TOKEN = args.token if args.token else "secret-bearer-token"

    if AUTH_TYPE == "apikey":
        if args.api_key:
            AUTH_API_KEY = args.api_key
        else:
            AUTH_API_KEY = secrets.token_urlsafe(24)
            generated.append("api-key")
    else:
        AUTH_API_KEY = args.api_key if args.api_key else "secret-api-key"

    # Find available port if not specified
    if PORT == 0:
        PORT = find_available_port()

    print(f"\n{'='*60}")
    print("Demo A2A Agent with Authentication (Issue #2002)")
    print(f"{'='*60}")
    print(f"Host: {host}")
    print(f"Port: {PORT}")
    print(f"Auth Type: {AUTH_TYPE}")
    if AUTO_REGISTER:
        print(f"Agent Name: {AGENT_NAME}")
    if generated:
        print(f"Auto-generated: {', '.join(generated)}")
    print()

    if AUTH_TYPE == "basic":
        print("Basic Auth Configuration:")
        print(f"  Username: {AUTH_USERNAME}")
        print(f"  Password: {AUTH_PASSWORD}", "(auto-generated)" if "password" in generated else "")
        print("\nTest with curl:")
        print(f'  curl -u {AUTH_USERNAME}:{AUTH_PASSWORD} http://localhost:{PORT}/run -X POST -H "Content-Type: application/json" -d \'{{"query": "calc: 5*10"}}\'')
        print("\nRegister with ContextForge using:")
        print("  auth_type: basic")
        print(f"  auth_username: {AUTH_USERNAME}")
        print(f"  auth_password: {AUTH_PASSWORD}")
    elif AUTH_TYPE == "bearer":
        print("Bearer Token Configuration:")
        print(f"  Token: {AUTH_TOKEN}", "(auto-generated)" if "token" in generated else "")
        print("\nTest with curl:")
        print(f'  curl -H "Authorization: Bearer {AUTH_TOKEN}" http://localhost:{PORT}/run -X POST -H "Content-Type: application/json" -d \'{{"query": "calc: 5*10"}}\'')
        print("\nRegister with ContextForge using:")
        print("  auth_type: bearer")
        print(f"  auth_token: {AUTH_TOKEN}")
    elif AUTH_TYPE == "apikey":
        print("X-API-Key Configuration:")
        print(f"  API Key: {AUTH_API_KEY}", "(auto-generated)" if "api-key" in generated else "")
        print("\nTest with curl:")
        print(f'  curl -H "X-API-Key: {AUTH_API_KEY}" http://localhost:{PORT}/run -X POST -H "Content-Type: application/json" -d \'{{"query": "calc: 5*10"}}\'')
        print("\nRegister with ContextForge using:")
        print("  auth_type: authheaders")
        print(f"  auth_headers: [{{'key': 'X-API-Key', 'value': '{AUTH_API_KEY}'}}]")
    else:
        print("No authentication required")
        print("\nTest with curl:")
        print(f'  curl http://localhost:{PORT}/run -X POST -H "Content-Type: application/json" -d \'{{"query": "calc: 5*10"}}\'')

    print("\nSupported queries:")
    print("  - calc: 5*10+2")
    print("  - weather: Dallas")
    print("  - echo: Hello World")
    print("\nPress Ctrl+C to stop\n")

    # Register cleanup handler
    if AUTO_REGISTER:
        atexit.register(unregister_agent)

    def signal_handler(sig, frame):
        print("\nShutting down...")
        if AUTO_REGISTER:
            unregister_agent()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Register with ContextForge if enabled
    if AUTO_REGISTER:
        register_agent(PORT)

    # Start the server
    uvicorn.run(app, host=host, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
