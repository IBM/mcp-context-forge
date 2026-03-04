# {{cookiecutter.plugin_name}} for ContextForge

{{cookiecutter.description}}.


## Installation

To install dependencies with dev packages (required for linting and testing):

```bash
make install-dev
```

Alternatively, you can also install it in editable mode:

```bash
make install-editable
```

## Setting up the development environment

1. Copy .env.template .env
2. Enable plugins in `.env`

## Testing

Test modules are created under the `tests` directory.

To run all tests, use the following command:

```bash
make test
```

**Note:** To enable logging, set `log_cli = true` in `tests/pytest.ini`.

## Code Linting

Before checking in any code for the project, please lint the code.  This can be done using:

```bash
make lint-fix
```

## Runtime (server)

This plugin server supports multiple transport protocols:

| Transport | Performance | Use Case |
|-----------|-------------|----------|
| `http` | ~600 calls/sec | Default, broad compatibility |
| `stdio` | ~600 calls/sec | Subprocess-based plugins |
| `grpc` | ~4,700 calls/sec | High-performance remote |
| `unix` | ~9,000 calls/sec | High-performance local IPC |

### Running with MCP (HTTP) - Default

```bash
# Install base dependencies
pip install .

# Run server
PLUGINS_TRANSPORT=http ./run-server.sh
```

### Running with gRPC (High Performance)

```bash
# Install with gRPC support
pip install ".[grpc]"

# Run server
PLUGINS_TRANSPORT=grpc ./run-server.sh
```

### Running with Unix Socket (Highest Performance)

```bash
# Install with gRPC support (for protobuf)
pip install ".[grpc]"

# Run server
PLUGINS_TRANSPORT=unix ./run-server.sh
```

### Container Build

To build the container image:

```bash
# Without gRPC support (smaller image)
make build

# With gRPC support
docker build --build-arg INSTALL_GRPC=true -t myplugin .
```

To run the container:

```bash
# Default (MCP/HTTP)
make start

# With gRPC
docker run -e PLUGINS_TRANSPORT=grpc -p 50051:50051 myplugin
```

To stop the container:

```bash
make stop
```
