#!/bin/bash

# Author: Mihai Criveti

# Exit on any error
set -e

# Default settings
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-4444}
ENV_FILE=${ENV_FILE:-.env}
LOG_LEVEL=${LOG_LEVEL:-info}
LOG_FORMAT=${LOG_FORMAT:-json}
RELOAD=${RELOAD:-false}
WORKERS=${WORKERS:-1}
ACCESS_LOG=${ACCESS_LOG:-true}
APP_MODULE=${APP_MODULE:-mcpgateway.main:app}

# Help message
show_help() {
    echo "MCP Gateway Runner"
    echo "==================="
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -h, --help           Show this help message"
    echo "  -e, --env FILE       Use specific env file (default: .env)"
    echo "  -H, --host HOST      Bind to HOST address (default: 0.0.0.0)"
    echo "  -p, --port PORT      Use PORT (default: 4444)"
    echo "  -l, --log LEVEL      Set log level: debug, info, warning, error, critical (default: info)"
    echo "  -f, --format FORMAT  Set log format: json or text (default: json)"
    echo "  -r, --reload         Enable auto-reload for development"
    echo "  -w, --workers N      Number of worker processes (default: 1)"
    echo "  -n, --no-access-log  Disable access log"
    echo "  -m, --module MODULE  Use specified app module (default: mcpgateway.main:app)"
    echo ""
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -e|--env)
            ENV_FILE="$2"
            shift 2
            ;;
        -H|--host)
            HOST="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -l|--log)
            LOG_LEVEL="$2"
            shift 2
            ;;
        -r|--reload)
            RELOAD=true
            shift
            ;;
        -w|--workers)
            WORKERS="$2"
            shift 2
            ;;
        -n|--no-access-log)
            ACCESS_LOG=false
            shift
            ;;
        -m|--module)
            APP_MODULE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Validate log level
if ! [[ "$LOG_LEVEL" =~ ^(debug|info|warning|error|critical)$ ]]; then
    echo "Invalid log level: $LOG_LEVEL"
    echo "Must be one of: debug, info, warning, error, critical"
    exit 1
fi

# Validate log format
if ! [[ "$LOG_FORMAT" =~ ^(json|text)$ ]]; then
    echo "Invalid log format: $LOG_FORMAT"
    echo "Must be one of: json, text"
    exit 1
fi

# Create default .env if it doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating default $ENV_FILE..."
    cat > "$ENV_FILE" << EOL
# Basic Settings
APP_NAME=MCP_Gateway
HOST=${HOST}
PORT=${PORT}
DATABASE_URL=sqlite:///./mcp.db
LOG_LEVEL=${LOG_LEVEL^^}
LOG_FORMAT=${LOG_FORMAT}

# Authentication
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
AUTH_REQUIRED=true
AUTH_ENCRYPTION_SECRET=my-test-salt

# Security
SKIP_SSL_VERIFY=false
ALLOWED_ORIGINS='["http://localhost", "http://localhost:${PORT}"]'
CORS_ENABLED=true

# Transport
TRANSPORT_TYPE=all
WEBSOCKET_PING_INTERVAL=30
SSE_RETRY_TIMEOUT=5000

# Federation
FEDERATION_TIMEOUT=30

# Resources
RESOURCE_CACHE_SIZE=1000
RESOURCE_CACHE_TTL=3600
MAX_RESOURCE_SIZE=10485760

# Tools
TOOL_TIMEOUT=60
MAX_TOOL_RETRIES=3
TOOL_RATE_LIMIT=100
TOOL_CONCURRENT_LIMIT=10

# Database
DB_POOL_SIZE=200
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# Development
DEV_MODE=$([ "$RELOAD" = "true" ] && echo "true" || echo "false")
EOL
fi

# Load environment variables
if [ -f "$ENV_FILE" ]; then
    echo "Loading environment from $ENV_FILE..."
    set -a
    source "$ENV_FILE"
    set +a
fi

# Create database directory if needed
if [[ "$DATABASE_URL" == sqlite:* ]]; then
    DB_PATH=$(echo "$DATABASE_URL" | sed -e 's/^sqlite:\/\///')
    DB_DIR=$(dirname "$DB_PATH")
    echo "Ensuring database directory exists: $DB_DIR"
    mkdir -p "$DB_DIR"
fi

# Build log configuration
if [ "$ACCESS_LOG" = "false" ]; then
    LOG_CONFIG="$LOG_CONFIG --no-access-log"
fi

# Check if running in development mode
if [ "$RELOAD" = "true" ]; then
    echo "Starting MCP Gateway in development mode..."
    echo "Running: uvicorn $APP_MODULE --host $HOST --port $PORT --reload $LOG_CONFIG"
    exec uvicorn $APP_MODULE \
        --host "$HOST" \
        --port "$PORT" \
        --reload \
        $LOG_CONFIG
else
    echo "Starting MCP Gateway in production mode..."
    echo "Running: uvicorn $APP_MODULE --host $HOST --port $PORT --workers $WORKERS $LOG_CONFIG"
    exec uvicorn $APP_MODULE \
        --host "$HOST" \
        --port "$PORT" \
        --workers "$WORKERS" \
        $LOG_CONFIG
fi
