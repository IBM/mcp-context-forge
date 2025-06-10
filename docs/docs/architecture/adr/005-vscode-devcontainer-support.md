# ADR-005: VS Code Dev Container Support

## Status

Accepted

## Context

New contributors to the MCP Context Forge project face significant setup friction when trying to get a development environment running. The manual setup process requires:

- Installing Python 3.11
- Installing Docker/Podman
- Setting up virtual environments
- Installing development dependencies
- Configuring environment variables
- Running tests to verify setup

This setup complexity can discourage contributions and slow down the onboarding process for new developers. Many contributors use VS Code or GitHub Codespaces, which support Dev Containers for standardized development environments.

## Decision

We will add VS Code Dev Container support to the project by implementing:

1. **`.devcontainer/devcontainer.json`** - Configuration specifying:
   - Container build instructions
   - VS Code extensions (Python, Docker)
   - Post-creation commands
   - Environment variables for development mode

2. **`.devcontainer/Dockerfile`** - Container definition with:
   - Python 3.11 slim base image
   - Docker CLI for container management
   - System dependencies (curl, git, build-essential)
   - Python tooling (pip, setuptools, pdm, uv)
   - Development environment setup

3. **`.devcontainer/postCreateCommand.sh`** - Setup script that:
   - Copies `.env.example` to `.env` if needed
   - Runs `make install-dev` to install development dependencies
   - Runs `make test` to verify the environment

4. **Documentation updates** - README.md section explaining:
   - How to use the devcontainer in VS Code
   - How to use with GitHub Codespaces
   - Benefits and included tools

## Consequences

### Positive

- **Instant onboarding**: New contributors can start developing immediately with one click
- **Consistent environments**: All developers use the same Python version, tools, and dependencies
- **Reduced setup friction**: No need to manually install Python, Docker, or configure environments
- **GitHub Codespaces support**: Cloud-based development without local setup requirements
- **Automated verification**: Tests run automatically to ensure the environment is working
- **Standardized tooling**: Everyone gets the same VS Code extensions and configuration

### Negative

- **Additional maintenance**: Need to keep devcontainer configuration in sync with project requirements
- **Container build time**: Initial setup takes a few minutes for first-time users
- **Docker dependency**: Requires Docker/Podman to be installed and running
- **Limited to VS Code**: Only benefits developers using VS Code or Codespaces

### Neutral

- **File size increase**: Adds minimal files to the repository
- **Learning curve**: Developers unfamiliar with Dev Containers may need to learn the workflow

## Alternatives Considered

1. **Manual setup instructions only** (current state)
   - Pros: No additional complexity
   - Cons: High setup friction, inconsistent environments

2. **Gitpod integration**
   - Pros: Cloud-based development
   - Cons: Less VS Code-native, additional external dependency

3. **Docker Compose for development**
   - Pros: Tool-agnostic
   - Cons: More complex setup, less integrated with VS Code

4. **Vagrant-based development environment**
   - Pros: Full VM isolation
   - Cons: Resource-heavy, slower, less modern workflow

## Implementation Details

The devcontainer uses:
- **Python 3.11**: As specified in the project requirements
- **PDM and UV**: For package management (matching the project's tooling)
- **Make targets**: Leverages existing `make install-dev` and `make test` workflows
- **Environment variables**: Sets `MCPGATEWAY_DEV_MODE=true` for development
- **VS Code extensions**: Includes Python and Docker extensions for optimal development experience

## Verification

The implementation was tested by:
1. Building the devcontainer in VS Code
2. Verifying that development dependencies install correctly
3. Confirming that the test suite passes
4. Checking that all Make targets work properly inside the container

## References

- [VS Code Dev Containers documentation](https://code.visualstudio.com/docs/devcontainers/containers)
- [GitHub Codespaces documentation](https://docs.github.com/en/codespaces)
- [Dev Container specification](https://containers.dev/)
- Project issue/PR requesting devcontainer support
