# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

## Quickstart

- Install (dev):
  - `python -m pip install -e .[dev]`
- Run (stdio):
  - `python -m {{ cookiecutter.package_name }}.server`
- Test:
  - `pytest -v`
- Makefile targets:
  - `make dev` -- runs stdio server
  - `make test` -- pytest with coverage
  - `make format` / `make lint`
  {%- if cookiecutter.include_http_bridge %}
  - `make serve-http` -- expose stdio server over HTTP via gateway translate
  - `make test-http` -- quick HTTP checks
  {%- endif %}

## MCP Client Snippet

Use this snippet in your MCP client configuration (e.g., Claude Desktop):

```json
{"command": "python", "args": ["-m", "{{ cookiecutter.package_name }}.server"], "cwd": "."}
```

## Container

Build and run with a local container runtime (Docker/Podman):

```bash
# Build
podman build -f Containerfile -t {{ cookiecutter.dist_name }}:{{ cookiecutter.version }} .
# Run
podman run --rm -it {{ cookiecutter.dist_name }}:{{ cookiecutter.version }}
```

## License

{{ cookiecutter.license }}
