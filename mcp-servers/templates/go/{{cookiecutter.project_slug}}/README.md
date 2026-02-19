# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

## Quick Start

```bash
# Build & run over stdio
make run
```

## Install

```bash
go install {{ cookiecutter.module_path }}@latest
```

## MCP Client Configuration (stdio)

```json
{
  "mcpServers": {
    "{{ cookiecutter.bin_name }}": {
      "command": "{{ cookiecutter.bin_name }}",
      "args": []
    }
  }
}
```

## Docker

```bash
# Build
podman build -t {{ cookiecutter.bin_name }}:{{ cookiecutter.version }} .
# Run (stdio mode in container)
podman run --rm -it {{ cookiecutter.bin_name }}:{{ cookiecutter.version }}
```

License: {{ cookiecutter.license }}
