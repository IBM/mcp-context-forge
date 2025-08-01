# Best Practices

## Input and output santitization

Ensure your inputs and outputs are sanitized. In Python, we recommend using Pydantic V2.

## 📦 Self-Containment
Each MCP server must be a **standalone repository** that includes all necessary code and documentation.
Example: `git clone; make serve`

## 🛠 Makefile Requirements

All MCP repositories must include a `Makefile` with the following standard targets. These targets ensure consistency, enable automation, and support local development and containerization.

### ✅ Required Make Targets

Make targets are grouped by functionality. Use `make help` to see them all in your terminal.

#### 🌱 VIRTUAL ENVIRONMENT & INSTALLATION

| Target           | Description |
|------------------|-------------|
| `make venv`      | Create a new Python virtual environment in `~/.venv/<project>`. |
| `make activate`  | Output the command to activate the virtual environment. |
| `make install`   | Install all dependencies using `uv` from `pyproject.toml`. |
| `make clean`     | Remove virtualenv, Python artifacts, build files, and containers. |

#### ▶️ RUN SERVER & TESTING

| Target               | Description |
|----------------------|-------------|
| `make serve`         | Run the MCP server locally (e.g., `mcp-time-server`). |
| `make test`          | Run all unit and integration tests with `pytest`. |
| `make test-curl`     | Run public API integration tests using a `curl` script. |

#### 📚 DOCUMENTATION & SBOM

| Target         | Description |
|----------------|-------------|
| `make docs`    | Generate project documentation and SBOM using `handsdown`. |
| `make sbom`    | Create a software bill of materials (SBOM) and scan dependencies. |

#### 🔍 LINTING & STATIC ANALYSIS

| Target               | Description |
|----------------------|-------------|
| `make lint`          | Run all linters (e.g., `ruff check`, `ruff format`). |

#### 🐳 CONTAINER BUILD & RUN

| Target               | Description |
|----------------------|-------------|
| `make podman`        | Build a production-ready container image with Podman. |
| `make podman-run`    | Run the container locally and expose it on port 8080. |
| `make podman-stop`   | Stop and remove the running container. |
| `make podman-test`   | Test the container with a `curl` script. |

#### 🛡️ SECURITY & PACKAGE SCANNING

| Target         | Description |
|----------------|-------------|
| `make trivy`   | Scan the container image for vulnerabilities using [Trivy](https://aquasecurity.github.io/trivy/). |

> **Tip:** These commands should work out-of-the-box after cloning a repo and running `make venv install serve`.

## 🐳 Containerfile

Each repo must include a `Containerfile` (Podman-compatible, Docker-compatible) to support containerized execution.

### Containerfile Requirements:

- Must start from a secure base (e.g., latest Red Hat UBI9 minimal image `registry.access.redhat.com/ubi9-minimal:9.5-1741850109`)
- Should use `uv` or `pdm` to install dependencies via `pyproject.toml`
- Must run the server using the same entry point as `make serve`
- Should expose relevant ports (`EXPOSE 8080`)
- Should define a non-root user for runtime

## 📚 Dependency Management
- All Python projects must use `pyproject.toml` and follow PEP standards.
- Dependencies must either be:
  - Included in the repo
  - Pulled from PyPI (no external links)

## 🎯 Clear Role Definition
- State the **specific role** of the server (e.g., GitHub tools).
- Group related tools together.
- **Do not mix roles** (e.g., GitHub ≠ Jira ≠ GitLab).

## 🧰 Standardized Tools
Each MCP server should expose tools that follow the MCP conventions, e.g.:

- `create_ticket`
- `create_pr`
- `read_file`

## 📁 Consistent Structure
Repos must follow a common structure. For example, from the time_server

```
time_server/
├── Containerfile                  # Container build definition (Podman/Docker compatible)
├── Makefile                       # Build, run, test, and container automation targets
├── pyproject.toml                 # Python project and dependency configuration (PEP 621)
├── README.md                      # Main documentation: overview, setup, usage, env vars
├── CONTRIBUTING.md                # Guidelines for contributing, PRs, and issue management
├── .gitignore                     # Exclude venvs, artifacts, and secrets from Git
├── docs/                          # (Optional) Diagrams, specs, and additional documentation
├── tests/                         # Unit and integration tests
│   ├── __init__.py
│   ├── test_main.py               # Tests for main entrypoint behavior
│   └── test_tools.py              # Tests for core tool functionality
└── src/                           # Application source code
    └── mcp_time_server/           # Main package named after your server
        ├── __init__.py            # Marks this directory as a Python package
        ├── main.py                # Entrypoint that wires everything together
        ├── mcp_server_base.py     # Optional base class for shared server behavior
        ├── server.py              # Server logic (e.g., tool registration, lifecycle hooks)
        └── tools/                 # Directory for all MCP tool implementations
            ├── __init__.py
            ├── tools.py           # Tool business logic (e.g., `get_time`, `format_time`)
            └── tools_registration.py # Registers tools into the MCP framework
```

## 📝 Documentation
Each repo must include:

- A comprehensive `README.md`
- Setup and usage instructions
- Environment variable documentation

## 🧩 Modular Design
Code should be cleanly separated into modules for easier maintenance and scaling.

## ✅ Testing
Include **unit and integration tests** to validate functionality.

## 🤝 Contribution Guidelines
Add a `CONTRIBUTING.md` with:

- How to file issues
- How to submit pull requests
- Review and merge process

## 🏷 Versioning and Releases
Use **semantic versioning**.
Include **release notes** for all changes.

## 🔄 Pull Request Process
Submit new MCP servers via **pull request** to the org's main repo.
PR must:

- Follow all standards
- Include all documentation

## 🔐 Environment Variables and Secrets
- Use environment variables for secrets
- Use a clear, role-based prefix (e.g., `MCP_GITHUB_`)

**Example:**

```env
MCP_GITHUB_ACCESS_TOKEN=...
MCP_GITHUB_BASE_URL=...
```

## 🏷 Required Capabilities (README Metadata Tags)

Add tags at the top of `README.md` between YAML markers to declare your server’s required capabilities.

### Available Tags:

- **`needs_filesystem_access`**
  Indicates the server requires access to the local filesystem (e.g., for reading/writing files).

- **`needs_api_key_user`**
  Requires a user-specific API key to interact with external services on behalf of the user.

- **`needs_api_key_central`**
  Requires a centrally managed API key, typically provisioned and stored by the platform.

- **`needs_database`**
  The server interacts with a persistent database (e.g., PostgreSQL, MongoDB).

- **`needs_network_access_inbound`**
  The server expects to receive inbound network requests (e.g., runs a web server or webhook listener).

- **`needs_network_access_outbound`**
  The server needs to make outbound network requests (e.g., calling external APIs or services).

### Example:

```markdown
---
tags:
  - needs_filesystem_access
  - needs_api_key_user
---
```