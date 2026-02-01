# Reviewing a Pull Request

This guide explains the day-to-day steps for **reviewing** a PR on GitHub, using both Git and the GitHub CLI (`gh`). It assumes you have already completed the one-time setup from the main [workflow guide](./github.md).

---

## 1. Prerequisites

You should already have:

- A local clone of the forked repository, with `origin` pointing to your fork and `upstream` pointing to the canonical repo.
- The GitHub CLI (`gh`) installed and authenticated.
- Your `main` branch up to date with upstream:

```bash
  git fetch upstream
  git switch main
  git merge --ff-only upstream/main
```

---

## 2. Fetching & Checking Out the PR

### 2.1 Using GitHub CLI

```bash
gh pr checkout <PR-number>
```

> This automatically fetches the PR and switches to a branch named `pr-<PR-number>`.

### 2.2 Using Plain Git

```bash
git fetch upstream pull/<PR-number>/head:pr-<PR-number>
git switch pr-<PR-number>
```

---

## 3. Smoke-Testing the Changes

Before you read code or leave comments, **always** verify the PR builds and tests cleanly.

### 3.1 Local Build

```bash
make install-dev serve   # Install into a fresh venv, and test it runs locally
```

### 3.2 Container Build and testing with Postgres and Redis (compose)

```bash
make docker-prod      # Build the lite runtime image locally
make compose-up       # Spins up the Docker Compose stack (PostgreSQL + Redis)

# Test the basics
curl http://localhost:4444/health         # {"status":"healthy"}
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key)
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/version | jq -c '.database, .redis'

# Add an MCP server to http://localhost:4444 then check logs:
make compose-logs
```

### 3.3 Automated Tests

```bash
make test           # or `pytest`
```

### 3.4 Lint & Static Analysis

```bash
make lint           # runs ruff, mypy, black --check, eslint, etc.
```

> **If any step fails**, request changes and paste the relevant error logs.

---

## 4. Functional & Code Review Checklist

Use this checklist as you browse the changes:

| Check                             | Why it matters                                     |
| --------------------------------- | -------------------------------------------------- |
| **Does it build locally?**        | Ensures no missing dependencies or compile errors. |
| **Does it build in Docker?**      | Catches environment-specific issues.               |
| **Tests are green?**              | Guards against regressions.                        |
| **No new lint errors?**           | Maintains code quality and consistency.            |
| **Commits are clean & signed?**   | One-commit history & DCO compliance.               |
| **Code follows style guidelines** | Consistency in formatting, naming, and patterns.   |
| **Security checks passed**        | No secrets leaked, inputs validated, etc.          |
| **Docs / comments updated?**      | Documentation stays in sync with code.             |
| **Edge cases & error handling**   | Robustness against invalid inputs or failures.     |

---

## 5. Leaving Feedback

### 5.1 Inline Comments

Use `gh pr review` to leave comments:

```bash
# To comment without approving
gh pr review --comment --body "Nit: rename this variable for clarity."

# To request changes
gh pr review --request-changes --body "Tests are failing on CI, please fix."

# To approve
gh pr review --approve --body "Looks good to me!"
```

### 5.2 Approving in the UI

1. On the PR page, click **"Files changed"**.
2. Hover over a line and click the **+** to leave an inline comment.
3. After addressing all comments, click **Review changes** → **Approve**.

---

## 6. Merging the PR (as a Maintainer)

> Only merge once all approvals, status checks, and CI jobs are green.

1. On GitHub, click **Merge pull request**.
2. Choose **Squash and merge** (default) or **Rebase and merge**.
3. Verify the commit title and body follow [Conventional Commits](https://www.conventionalcommits.org/).
4. Confirm the **Signed-off-by** trailer is present.
5. Click **Confirm merge**.

GitHub will delete the `pr-<number>` branch automatically.

---

## 7. Cleaning Up Locally
After the PR is merged:

* Switch back to the main branch
* Delete the local feature branch
* Prune deleted remote branches
```bash
git switch main
git branch -D pr-<PR-number>             # replace <PR-number> with your branch name
git fetch -p                             # prune deleted remotes
```
This removes references to remote branches that GitHub deleted after the merge.
This keeps your local environment clean and up to date.

---
