# docs/AGENTS.md

Documentation authoring guidance for AI coding assistants.

This directory contains the project's architecture and usage documentation built with MkDocs.

## Directory Structure

```
docs/
├── mkdocs.yml          # MkDocs configuration
├── base.yml            # Base configuration
├── Makefile            # Doc build automation
├── requirements.txt    # Doc dependencies
├── theme/              # Custom theme assets
└── docs/               # Documentation content
    ├── index.md        # Home page
    ├── architecture/   # System design, ADRs, plugins, security
    ├── deployment/     # Docker, K8s, cloud guides
    ├── development/    # Developer guides, building, testing
    ├── manage/         # Operations, API usage, logging, scaling
    ├── using/          # User guides (agents, clients, servers)
    ├── testing/        # Test guides, performance, fuzzing
    ├── best-practices/ # Best practice guides
    ├── tutorials/      # Step-by-step tutorials
    ├── overview/       # Project overview
    ├── faq/            # FAQ
    └── coverage/       # Generated coverage reports
```

## Quick Commands

From `docs/` directory:

```bash
# Install dependencies
pip install -r requirements.txt

# Build docs
make build                # Build static site

# Serve locally
make serve                # Serve at http://localhost:8001

# Clean
make clean                # Remove build artifacts
```

From repository root:

```bash
make docs                 # Build documentation
make docs-serve           # Serve documentation locally
```

## Writing Documentation

### File Location

Place documentation in the appropriate subdirectory:

| Topic | Directory |
|-------|-----------|
| System design, ADRs | `docs/architecture/` |
| Deployment guides | `docs/deployment/` |
| Developer guides | `docs/development/` |
| Operations guides | `docs/manage/` |
| User guides | `docs/using/` |
| Test documentation | `docs/testing/` |

### Markdown Conventions

- Use ATX-style headers (`#`, `##`, `###`)
- Include front matter for navigation title if needed
- Use fenced code blocks with language hints
- Keep lines under 120 characters when practical

### Code Examples

Use fenced code blocks with language identifier:

```python
from mcpgateway import Gateway

gateway = Gateway()
gateway.start()
```

### Admonitions

```markdown
!!! note
    This is a note.

!!! warning
    This is a warning.

!!! tip
    This is a tip.
```

### Internal Links

```markdown
See [Configuration Reference](manage/configuration.md) for details.
See [Architecture Overview](architecture/index.md).
```

## Navigation

Navigation is configured in `mkdocs.yml`. When adding new pages:

1. Create the markdown file in the appropriate directory
2. Add an entry to the `nav` section in `mkdocs.yml`

## API Documentation

API documentation is auto-generated from OpenAPI schema:
- Swagger UI: `http://localhost:4444/docs`
- OpenAPI JSON: `http://localhost:4444/openapi.json`

## Coverage Reports

Coverage reports are generated to `docs/docs/coverage/`:

```bash
make htmlcov              # Generate HTML coverage report
```

## Key Documentation Pages

- `docs/development/developer-onboarding.md` - New contributor guide
- `docs/development/building.md` - Build system and testing
- `docs/manage/api-usage.md` - REST API guide
- `docs/architecture/index.md` - Architecture overview
- `docs/architecture/adr/` - Architecture Decision Records

## Important Notes

- Do not create documentation files unless explicitly requested
- Prefer editing existing files over creating new ones
- Keep documentation up-to-date with code changes
- Use relative links for internal references
