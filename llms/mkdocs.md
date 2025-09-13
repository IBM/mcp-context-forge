MkDocs: Building and Serving Documentation

- Purpose: Quick, accurate instructions for LLMs to help users preview, build, and publish the documentation site.
- Scope: MkDocs project under `docs/` using MkDocs Material and plugins; includes local venv, live preview, static builds, and deploy.

**Project Layout**
- Root: repository code, app Makefile, tests, etc.
- Docs site: `docs/`
  - `docs/docs/`: Markdown content (place pages here)
  - `docs/mkdocs.yml`: MkDocs configuration (site settings, plugins)
  - `docs/Makefile`: docs-specific targets (venv, serve, build, deploy)
  - `docs/base.yml`, `docs/theme/`: shared settings and theme assets

Notes
- Author content only under `docs/docs/` and its subfolders.
- Left-nav ordering is controlled per-directory via `.pages` files (see `docs/docs/development/documentation.md`).

**First-Time Setup (Docs venv)**
- Python 3.11+ and GNU Make required.
- Create the MkDocs virtual environment (installed under `~/.venv/mcpgateway-docs`):
  - `cd docs`
  - `make venv`
  - To update later: `make venv-update`
- Activate venv (optional, the Makefile sources it automatically):
  - `. ~/.venv/mcpgateway-docs/bin/activate`

**Live Preview (Hot Reload)**
- From `docs/` run:
  - `make serve`
- Opens MkDocs server at `http://127.0.0.1:8000` with auto-reload on save.
- Port busy? Run MkDocs directly with a custom port:
  - `~/.venv/mcpgateway-docs/bin/mkdocs serve --dev-addr=127.0.0.1:8001`

**Static Builds**
- From `docs/`:
  - `make build`
    - Produces a full site and exports a combined HTML/Word output to `docs/site/out/` (via Pandoc).
  - `make package`
    - Builds site and packages sources as a tarball under `docs/release/`.

**Deploy to GitHub Pages**
- From `docs/`:
  - `make deploy` (runs `mkdocs gh-deploy`)

**Root-Level Helpers (Optional)**
- Some repository-wide targets enrich docs content:
  - `make htmlcov` (root) writes coverage HTML to `docs/docs/coverage/`.
  - `make coverage` (root) generates `docs/docs/test/unittest.md` and badges.
  - `make docs` (root) builds images/SBOM and copies `README.md` to `docs/docs/index.md`.

**Quality & Linting**
- Prefer keeping docs consistent with the project's quality workflow:
  - `make autoflake isort black pre-commit` (root) to format Python, sort imports, and run hooks.
  - Additional docs authoring guidance: `docs/docs/development/documentation.md`.

**Common Tips**
- Keep file names in `lowercase-hyphen-case.md` and start with a top-level `# Heading`.
- Use relative links and keep images under `docs/docs/images/`.
- Do not directly edit `mkdocs.yml` navigation; manage per-folder navigation via `.pages`.
