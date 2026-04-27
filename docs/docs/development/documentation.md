# Writing & Publishing Documentation

Follow this guide when you need to add or update markdown pages under `docs/` and preview the documentation locally.

---

## 🧩 Prerequisites

* **Python ≥ 3.11** (only for the initial virtual env - *not* required if you already have one)
* `make` (GNU Make 4+)
* (First-time only) **[`mkdocs-material`](https://squidfunk.github.io/mkdocs-material/)** and plugins are installed automatically by the *docs* `Makefile`.
* One-time GitHub setup, e.g. [gitconfig setup](./github.md#16-personal-git-configuration-recommended)

---

## ⚡ One-liner for a live preview

```bash
cd docs
make venv     # First-time only, installs dependencies into a venv under `~/.venv/mcpgateway-docs`
make serve    # http://localhost:8003 (auto-reload on save)
```

*The `serve` target automatically creates a project-local virtual environment (under `~/.venv/mcpgateway-docs`) the first time you run it and installs all doc dependencies before starting **MkDocs** in live-reload mode.*

---

## 📂 Folder layout

```text
repo-root/
├─ docs/              # MkDocs project (DO NOT put .md files here!)
│  ├─ docs/           # <-- ────────────▶  place Markdown pages here
│  │  └─ ...
│  ├─ mkdocs.yml      # MkDocs config & navigation
│  └─ Makefile        # build / serve / clean targets
└─ Makefile           # repo-wide helper targets (lint, spellcheck, ...)
```

* **Add new pages** inside `docs/docs/` - organise them in folders that make sense for navigation.
* **Update navigation**: edit `.pages` for your section so your page shows up in the left-hand nav.

> **Tip:** MkDocs Material auto-generates "Edit this page" links - keep file names lowercase-hyphen-case.

---

## ✏️ Editing tips

1. Write in **standard Markdown**; we also support admonitions, call-outs, and Mermaid diagrams.
2. Use relative links between pages: `[Configuration](../manage/configuration.md)`.
3. For local images place them under `docs/docs/images/` and reference with `![](../images/mcpgateway.svg)` (example asset in repo).
4. Never edit `mkdocs.yml` - all nav structure is defined in `.pages` files (one per directory).

---

## ✏️ Writing docs

Start each new Markdown file with a clear **`# Heading 1`** title - this becomes the visible page title and is required for proper rendering in MkDocs.

Follow the conventions and layout guidelines from the official **[MkDocs Material reference](https://squidfunk.github.io/mkdocs-material/reference/)** for callouts, tables, code blocks, and more. This ensures consistent formatting across the docs.

Keep file names in `lowercase-hyphen-case.md` and use relative links when referencing other docs or images.

---

## 🗂️ Ordering pages with `.pages`

For directories that contain multiple Markdown files, we rely on the [awesome-pages](https://henrywhitaker3.github.io/mkdocs-material-dark-theme/plugins/awesome-pages/) MkDocs plugin.

Creating a `.pages` file inside a folder lets you:

* **Set the section title** (different from the folder name).
* **Control the left-nav order** without touching the root `mkdocs.yml`.
* **Hide** specific files from the navigation.

We do **not** auto-generate the `nav:` structure - you must create `.pages` manually.

Example - *docs for the **development** section:*

```yaml
# docs/docs/development/.pages
# This file affects ONLY this folder and its sub-folders

# Optional: override the title shown in the nav
# title: Development Guide

nav:

  - index.md        # ➟ /development/ (landing page)
  - github.md       # contribution workflow
  - building.md     # local build guide
  - packaging.md    # release packaging steps
```

Guidelines:

1. Always include `index.md` first so the folder has a clean landing URL.
2. List files **in the exact order** you want them to appear; anything omitted is still built but won't show in the nav.
3. You can nest `.pages` files in deeper folders - rules apply hierarchically.
4. Avoid circular references: do **not** include files from *other* directories.

After saving a `.pages` file, simply refresh the browser running `make serve`; MkDocs will hot-reload and the navigation tree will update instantly.

---



## ✅ Pre-commit checklist

From the **repository root** run **all** lint & QA checks before pushing:

```bash
make spellcheck           # Spell-check the codebase
make spellcheck-sort      # Sort local spellcheck dictionary
make markdownlint         # Lint Markdown files with markdownlint (requires markdownlint-cli)
make pre-commit           # Run all configured pre-commit hooks
```

> These targets are defined in the top-level `Makefile`. Make sure you're in the repository root when running these targets.

---

## 🧹 Cleaning up

```bash
cd docs
make clean       # remove generated site/
make git-clean   # remove ignored files per .gitignore
make git-scrub   # blow away *all* untracked files - use with care!
```

---

## 🔄 Rebuilding the static site

> This is not necessary, as this will be done automatically when publishing.

```bash
cd docs
make build    # outputs HTML into docs/site/
```

---

## 🧭 Generated architecture diagrams

When the architecture changes, regenerate the design diagrams and update the tracked SVGs:

```bash
# From repo root
make images    # generate diagrams only
# or
make docs      # runs images + SBOM + docs helpers
```

Tracked outputs:

- `docs/docs/design/images/classes.svg` (class diagram)
- `docs/docs/design/images/packages.svg` (package diagram)


Commit updated SVGs when they change so the architecture pages stay current.

---

## 🔗 Internal link checks

MkDocs will warn on broken internal links and missing anchors. Before opening a PR:

```bash
cd docs
make serve    # watch console warnings while browsing pages
```

The `build` target produces a fully-static site (used by CI for docs previews and by GitHub Pages).

---

## 📤 Publishing Versioned Documentation

Documentation is deployed using [mike](https://github.com/jimporter/mike) for version management. Each release gets its own versioned documentation snapshot.

### Versioning Strategy

- **Single source**: Docs maintained in `main` branch alongside code
- **Deploy on release**: When cutting a version tag, deploy docs to that version
- **Frozen snapshots**: Each version folder (`1.0.0/`, `1.0.1/`) is immutable after deployment
- **Version selector**: Users can switch between versions via UI dropdown

### Deployment Commands

```bash
cd docs

# Deploy stable release (e.g., 1.0.0)
make mike-deploy VERSION=1.0.0
make mike-set-default

# Deploy release candidate
make mike-deploy VERSION=1.0.0-RC1

# Deploy development preview
make mike-deploy VERSION=dev

# List all deployed versions
make mike-list

# Delete a version
make mike-delete VERSION=0.8.0
```

### Release Workflow

When cutting a release tag (e.g., `v1.0.0`):

1. Ensure docs in `main` are up-to-date
2. Tag the release: `git tag -s v1.0.0`
3. Deploy versioned docs:
   ```bash
   cd docs
   make mike-deploy VERSION=1.0.0
   make mike-set-default
   ```

### Version Aliases

- `latest` → newest release (auto-updated)
- `stable` → production-ready version
- `dev` → development docs (optional)

### CI Integration

The `.github/workflows/docs-deploy.yml` workflow auto-deploys docs on push to `docs/**` or manual trigger with version input.

**Manual trigger:**
1. Go to Actions → "Deploy Docs with Mike"
2. Click "Run workflow"
3. Enter version (e.g., `1.0.0` or `latest`)
4. Run

### Local Preview

Preview versioned docs locally:

```bash
cd docs
make mike-serve  # http://localhost:8000 with version selector
```

### Architecture

- **Source**: `docs/docs/*.md` (main branch)
- **Built HTML**: `gh-pages` branch (managed by mike)
- **Structure**: `gh-pages/1.0.0/`, `gh-pages/0.9.0/`, etc.
- **Manifest**: `gh-pages/versions.json` (auto-managed)

!!! note "No version branches needed"
    Unlike traditional versioning strategies, we don't maintain separate `release/1.0` branches for docs. The `main` branch is the single source of truth, and mike creates versioned snapshots on `gh-pages` at release time.

---

## 🔗 Related reading

* [Building Locally](building.md) - how to run the gateway itself
