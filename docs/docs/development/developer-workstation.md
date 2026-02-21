# Developer Workstation

This guide helps you to set up your local environment for contributing to the Model Context Protocol (MCP) Gateway. It provides detailed instructions for tooling requirements, OS-specific notes, common pitfalls, and commit signing practices.

## Tooling Requirements

-   **Python** (>= 3.11)

    -   Download from [python.org](https://www.python.org/downloads/) or use your package manager (e.g., `brew install python` on macOS, `sudo apt-get install python3` on Ubuntu).
    -   Verify: `python3 --version`.

-   **Docker or Podman**

    -   **Docker**: Install `docker.io`, `buildx`, and `docker-compose v2`.

        -   [Docker Desktop](https://www.docker.com/products/docker-desktop/) for macOS/Windows.
        -   Linux: `sudo apt-get install docker.io docker-buildx-plugin docker-compose-plugin` (Debian/Ubuntu) or `sudo dnf install docker docker-buildx docker-compose` (Fedora).

    -   **Podman**: Install [Podman Desktop](https://podman-desktop.io/downloads) for a rootless alternative.
    -   Verify: `docker --version` or `podman --version`.

-   **Permissions Setup**

    -   **Docker**: Add your user to the `docker` group: `sudo usermod -aG docker $USER`, then log out and back in (Linux). Restart Docker Desktop (Windows/macOS).
    -   **Podman**: Configure rootless mode with `podman system service`.

-   **Docker Compose or Compatible Wrapper**

    -   Included with Docker Desktop or as `docker-compose-plugin`.
    -   For Podman: `pip install podman-compose`.
    -   Verify: `docker compose version` or `podman-compose --version`.

-   **GNU Make**

    -   macOS: `brew install make`.
    -   Linux: `sudo apt-get install make` or `sudo dnf install make`.
    -   Windows: Install via [Chocolatey](https://chocolatey.org/) (`choco install make`) or use WSL2.
    -   Verify: `make --version`.

-   **(Optional) uv, ruff, mypy, isort**

    -   Install: `pip install uv ruff mypy isort`.
    -   Usage: Run `ruff check .` or `mypy .` for linting/type checking.

-   **Node.js and npm** (for UI linters)

    -   Install from [nodejs.org](https://nodejs.org/).
    -   Verify: `node --version` and `npm --version`.
    -   Install linters: `npm install -g eslint stylelint`.

-   **(Optional)Visual Studio Code and useful plugins**

    -   Download from [code.visualstudio.com](https://code.visualstudio.com/).

## OS-Specific Setup

### macOS

-   **Installation**:

    -   Install [Homebrew](https://brew.sh/): `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`.
    -   Run: `brew install python docker make node`.

-   **Apple Silicon**: Use Docker Desktop with ARM64 support. Homebrew handles architecture natively.
-   **Troubleshooting**: Ensure Rosetta 2 is installed for Intel-based tools if needed (`softwareupdate --install-rosetta`).

### Linux

-   **Installation**:

    -   Debian/Ubuntu: `sudo apt-get update && sudo apt-get install python3 docker.io docker-buildx-plugin docker-compose-plugin make nodejs npm`.
    -   Fedora: `sudo dnf install python3 docker docker-buildx docker-compose make nodejs npm`.

-   **Permissions**: Add user to `docker` group: `sudo usermod -aG docker $USER`, then reboot.
-   **Troubleshooting**: Use `systemctl start docker` if the service isn't running.

### Windows

-   **Recommended: WSL2**

    -   Install [WSL2](https://docs.microsoft.com/en-us/windows/wsl/install) and Ubuntu: `wsl --install`.
    -   Install Docker Desktop with WSL2 integration.

-   **File Paths and Volume Mounting**

    -   Use forward slashes (e.g., `/f/All/ibm/mcp-forge/mcp-context-forge`).
    -   Avoid spaces/special characters; use absolute paths in `docker run -v`.

-   **Podman in WSL2**

    -   Install: `sudo apt-get install podman` in WSL2.
    -   Port exposure: Use `podman system service` and configure firewall (`sudo ufw allow 4444`).

-   **Windows Terminal**

    -   Install from Microsoft Store. set WSL2 as default profile.

-   **Make Alternatives**

    -   Use WSL2's `make` or install via Chocolatey (`choco install make`).

## Common Gotchas

### Docker Socket Permissions

-   **Problem**: You may encounter "permission denied while connecting to the Docker daemon" if your user lacks access to the Docker socket.
-   **Fix**:

    -   **Linux**: Add your user to the `docker` group with `sudo usermod -aG docker $USER`, then log out and log back in. Verify with `docker ps`.
    -   **Windows/macOS**: Restart Docker Desktop from the system tray or settings menu.

-   **Troubleshooting**: If the issue persists, ensure the Docker service is running (`systemctl status docker` on Linux) or reinstall Docker Desktop.

### .venv Activation Across Shells

-   **Problem**: The virtual environment (`.venv`) may not activate automatically when opening new terminal sessions.
-   **Fix**:

    -   **Activate**: Use `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows) for each session.
    -   **Persist**: Add to your shell profile (e.g., `echo "source ./.venv/bin/activate" >> ~/.bashrc` for Bash on Linux). Replace `.` with the relative path to your `.venv` if different.

-   **Troubleshooting**: Verify activation with `which python` (should point to `.venv/bin/python`); deactivate with `deactivate` if needed.

### Port 4444 Already in Use

-   **Problem**: Port 4444, used by the ContextForge and MkDocs, may be occupied by another process, causing conflicts.
-   **Fix**:

    -   **Check**: Run `netstat -aon | findstr :4444` (Windows) or `ss -tuln | grep 4444` (Linux) to identify the process ID (PID).
    -   **Resolve**: Use a different port for MkDocs with `mkdocs serve --dev-addr=127.0.0.1:8001`, or stop the conflicting process (e.g., `taskkill /PID <PID>` on Windows or `kill <PID>` on Linux).

-   **Troubleshooting**: If unsure which process to stop, check with `docker ps` (if a container) or review running services.

## Snippet Examples

### Set Up and Serve Documentation

```bash
# Build docs in an isolated environment
cd docs
make venv          # first run only; installs MkDocs + plugins
make serve         # http://127.0.0.1:8000 with live reload
```

## Local Keycloak SSO (Development)

Use the SSO compose profile when you want to test login and role mapping behavior locally.

### Start the stack

```bash
make compose-sso
```

Optional smoke check:

```bash
make sso-test-login
```

### Default local credentials

- Keycloak admin console: `http://localhost:8180`
- Keycloak admin user: `admin`
- Keycloak admin password: `changeme`
- Gateway login page: `http://localhost:8080/admin/login`
- Keycloak realm: `mcp-gateway`
- Keycloak client: `mcp-gateway`

Pre-seeded test users (all use password `changeme`):

- `admin@example.com` (realm role `gateway-admin`)
- `developer@example.com` (realm role `gateway-developer`)
- `viewer@example.com` (realm role `gateway-viewer`)
- `newuser@example.com` (no explicit `gateway-*` role; used to test default-role behavior)

### Login flow

1. Open `http://localhost:8080/admin/login`.
2. Click `Continue with Keycloak`.
3. Sign in with one of the test users above.
4. After callback to the gateway, validate role behavior in Admin UI/API.

If you land back on `.../admin/login?error=sso_failed`, re-run:

```bash
make sso-test-login
```

This verifies provider discovery, test users, and the full browser callback redirect to `/admin`.

For full provider configuration details, see [Keycloak OIDC Setup Tutorial](../manage/sso-keycloak-tutorial.md).

## Signing commits

To ensure commit integrity and comply with the DCO, sign your commits with a `Signed-off-by` trailer. Configure your Git settings:

```
# ~/.gitconfig
[user]
    name = Your Name
    email = your-email@example.com

[init]
    defaultBranch = main  # Use 'main' instead of 'master' when creating new repos

[core]
    autocrlf = input       # On commit: convert CRLF to LF (Windows → Linux)
                           # On checkout: leave LF alone (no conversion)
    eol = lf               # Ensure all files in the repo use LF internally

[alias]
    cm = commit -s -m      # Short alias: 'git cm "message"' creates signed-off commit
    ca = commit --amend -s # Amend last commit and ensure it has a Signed-off-by trailer

[commit]
    template = ~/.git-commit-template
```

-   **Setup**: Replace Your Name and your-email@example.com with your details.
-   **Signing**: Use git cm "Your message" to create signed commits automatically with the configured alias.
-   **Sign-off**: Use git commit -s -m "Your message" for manual signed commits without the alias.
