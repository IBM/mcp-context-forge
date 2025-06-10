# Writing & Publishing Documentation

Follow this guide when you need to add or update markdown pages under `docs/` and preview the documentation locally.

---

## 🧩 Prerequisites

* **Python ≥ 3.10** (only for the initial virtual env – *not* required if you already have one)
* `make` (GNU Make 4+)
* (First-time only) **[`mkdocs-material`](https://squidfunk.github.io/mkdocs-material/)** and plugins are installed automatically by the *docs* `Makefile`.
* One-time GitHub setup, e.g. [gitconfig setup](./github.md#16-personal-git-configuration-recommended)

---

## ⚡ One-liner for a live preview

```bash
cd docs
make venv     # First-time only, installs dependencies into a venv under `~/.venv/mcpgateway-docs`
make serve    # http://localhost:8000 (auto-reload on save)
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
└─ Makefile           # repo-wide helper targets (lint, spellcheck, …)
```

* **Add new pages** inside `docs/docs/` – organise them in folders that make sense for navigation.
* **Update navigation**: edit `.pages` for your section so your page shows up in the left-hand nav.

> **Tip:** MkDocs Material auto-generates "Edit this page" links – keep file names lowercase-hyphen-case.

---

## ✏️ Editing tips

1. Write in **standard Markdown**; we also support admonitions, call-outs, and Mermaid diagrams.
2. Use relative links between pages: `[Gateway API](../api/index.md)`.
3. For local images place them under `docs/docs/images/` and reference with `![](../images/example.png)`.
4. Never edit `mkdocs.yml` - all nav structure is defined in `.pages` files (one per directory).

---

## ✏️ Writing docs

Start each new Markdown file with a clear **`# Heading 1`** title – this becomes the visible page title and is required for proper rendering in MkDocs.

Follow the conventions and layout guidelines from the official **[MkDocs Material reference](https://squidfunk.github.io/mkdocs-material/reference/)** for callouts, tables, code blocks, and more. This ensures consistent formatting across the docs.

Keep file names in `lowercase-hyphen-case.md` and use relative links when referencing other docs or images.

---

## 🗂️ Ordering pages with `.pages`

For directories that contain multiple Markdown files, we rely on the [awesome-pages](https://henrywhitaker3.github.io/mkdocs-material-dark-theme/plugins/awesome-pages/) MkDocs plugin.

Creating a `.pages` file inside a folder lets you:

* **Set the section title** (different from the folder name).
* **Control the left‑nav order** without touching the root `mkdocs.yml`.
* **Hide** specific files from the navigation.

We do **not** auto-generate the `nav:` structure – you must create `.pages` manually.

Example – *docs for the **development** section:*

```yaml
# docs/docs/development/.pages
# This file affects ONLY this folder and its sub‑folders

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
3. You can nest `.pages` files in deeper folders – rules apply hierarchically.
4. Avoid circular references: do **not** include files from *other* directories.

After saving a `.pages` file, simply refresh the browser running `make serve`; MkDocs will hot‑reload and the navigation tree will update instantly.

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
make git-scrub   # blow away *all* untracked files – use with care!
```

---

## 🔄 Rebuilding the static site

> This is not necessary, as this will be done automatically when publishing.

```bash
cd docs
make build    # outputs HTML into docs/site/
```

The `build` target produces a fully-static site (used by CI for docs previews and by GitHub Pages).

---

## 📤 Publishing (CI)

Docs are tested, but not deployed automatically by GitHub Actions on every push to `main`. The workflow runs `cd docs && make build`.

Publishing is done manually by repo maintainers with `make deploy` which publishes the generated site to **GitHub Pages**.

---

## 🔗 Related reading

* [Building Locally](building.md) – how to run the gateway itself
