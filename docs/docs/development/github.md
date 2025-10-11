# GitHub Workflow Guide

This mini-handbook covers the daily Git tasks we use on **mcp-context-forge** - from the first clone to the last merge.

---

## 1. One-Time Setup

```bash
# Fork on GitHub from https://github.com/IBM/mcp-context-forge.git first, then:
git clone https://github.com/<your-user>/mcp-context-forge.git
cd mcp-context-forge

# Add the canonical repo so you can pull upstream changes
git remote add upstream https://github.com/IBM/mcp-context-forge.git
git remote -v   # sanity-check remotes
```

---

## 1.5 Installing GitHub CLI (`gh`)

### macOS (Homebrew)

```bash
brew install gh
```

### Windows (winget)

> While you can run all this through Powershell, the recommended way to develop on Windows is through WSL2 and Visual Studio Code.
> The same steps as Ubuntu/Debian apply.

```powershell
winget install GitHub.cli
```

### Ubuntu / Debian

```bash
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
  sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
  sudo tee /etc/apt/sources.list.d/github-cli.list

sudo apt update
sudo apt install gh
```

### Fedora / RHEL

```bash
sudo dnf install 'https://github.com/cli/cli/releases/download/v2.74.0/gh_2.74.0_linux_amd64.rpm'
```

> **Tip:** Replace the version number (`2.74.0`) with the latest release from [https://github.com/cli/cli/releases](https://github.com/cli/cli/releases).

### First-time authentication

```bash
gh auth login             # follow the interactive prompts
```

Choose:

1. **GitHub.com**
2. **HTTPS**
3. Either **Paste an authentication token** or **Authorize in browser**.

### Verify configuration

```bash
gh auth status            # should say "Logged in to github.com as <your-user>"
gh repo view              # shows repo info if run inside a clone
```

### Everyday commands

| Command               | Purpose                                                 |
| --------------------- | ------------------------------------------------------- |
| `gh pr checkout <id>` | Fetch & switch to a PR locally (used in §4).            |
| `gh pr create -w`     | Create a PR and open it in the browser.                 |
| `gh pr status`        | Show which PR is checked out and any requested reviews. |
| `gh pr merge <id>`    | Squash / rebase / merge the PR from the terminal.       |

---

## 1.6 Personal Git Configuration (Recommended)

Setting a few global Git options makes everyday work friction-free and guarantees that every commit passes DCO checks.

### 1.6.1 Commit template

Create a single-line template that Git pre-pends to every commit message so you never forget the sign-off:

```bash
echo 'Signed-off-by: <Your Name> <you@example.com>' > ~/.git-commit-template
```

### 1.6.2 `~/.gitconfig` example

Put this in `~/.gitconfig` (or append the bits you're missing):

```ini
# ~/.gitconfig
[user]
    name = <Your Name>
    email = <you@example.com>

[init]
    defaultBranch = main  # Use 'main' instead of 'master' when creating new repos

[core]
    autocrlf = input       # On commit: convert CRLF to LF (Windows → Linux)
    eol = lf               # Ensure all files in the repo use LF internally

[alias]
    cm = commit -s -m      # `git cm "message"` → signed commit
    ca = commit --amend -s # `git ca` → amend + sign-off

[commit]
    template = ~/.git-commit-template
```

Or run the one-liners:

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global alias.cm   "commit -s -m"
git config --global alias.ca   "commit --amend -s"
git config --global commit.template ~/.git-commit-template
```

Replace placeholders with your real details, and you're good to go.

---

## 2. Staying in Sync with Upstream

```bash
# From any branch:
git fetch upstream
git switch main                 # or master, depending on the project
git merge --ff-only upstream/main

git push origin main             # keep your fork up to date
```

---

## 3. Creating Your Own Work Branch

```bash
git switch -c feat/my-great-idea
# ...hack away...
git add .
# Always sign your commits for DCO compliance:
git commit -s -m "feat: explain context-merging algorithm"

git push -u origin HEAD          # publishes the branch
# Then open a Pull Request (PR) on GitHub.
```

> **Why `-s`?** The `-s / --signoff` flag appends a `Signed-off-by: Your Name <email>` trailer that lets CI verify Developer Certificate of Origin (DCO) compliance.

---

## 4. Fetching & Reviewing an Existing PR

### 4.1 With Plain Git (works everywhere)

```bash
git fetch upstream pull/29/head:pr-29   # Pull Request #29
git switch pr-29
```

### 4.2 With GitHub CLI (fastest if installed)

```bash
gh pr checkout 29
```

---

## 5. Smoke-Testing Every PR **Before** You Comment 🌋

> **Hard rule:** No PR gets a "Looks good to me" without passing both the **local** and **container** builds below.

### 5.1 Local build (SQLite + self-signed HTTPS)

```bash
make install-dev serve-ssl
```

* Sets up a Python virtualenv
* Installs runtime + dev dependencies
* Runs the HTTPS dev server against SQLite

### 5.2 Container build (PostgreSQL + Redis)

```bash
make docker-prod      # build the lite runtime image locally
make compose-up       # start the Docker Compose stack (PostgreSQL + Redis)
```

* Spins up the full Docker Compose stack
* Uses PostgreSQL for persistence and Redis for queueing
* Rebuilds/uses your freshly built image so you catch Docker-specific issues

### 5.3 Gateway JWT (local API access)

Quickly confirm that authentication works and the gateway is healthy:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret my-test-key)
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/health
```

Expected output:

```json
{"status": "healthy"}
```

If you see anything other than `{"status":"healthy"}`, investigate before approving the PR.

Quickly confirm that the MCP Gateway is configured with the correct database, and it is reachable:

```bash
curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" http://localhost:4444/version | jq
```

Then proceed to register an MCP Server under Gateways using the UI, ensuring that Tools work, creating a Virtual Server and testing that from UI, API and a MCP Client.

These steps are described in [Basic Testing](../testing/basic.md).

### 5.4 Run the automated test suite

```bash
make test         # or `pytest` directly
```

All tests **must** pass locally. If you add or modify functionality, ensure new tests cover the change.

### 5.5 Lint & static analysis

```bash
make lint         # runs ruff, mypy, black --check, etc.
```

Code should come back clean. Fix any warnings before pushing.

If **any** of the above steps fail, leave a review requesting fixes and paste the relevant logs inline or as a gist.

---

## 6. Squashing Commits 🥞

Keeping a clean, single-commit history per PR makes `git bisect` and blame easier.

### 6.1 Squash interactively (local, recommended)

```bash
# In your feature branch, before pushing OR after addressing review feedback:

git fetch upstream  # make sure refs are fresh
git rebase -i upstream/main
```

In the interactive list, mark the first commit as **`pick`** and every subsequent one as **`squash`** (or **`fixup`** for no extra message). Save & quit; Git opens an editor so you can craft the final commit message-remember to keep the `Signed-off-by` line!

If the branch is already on GitHub and you've squashed locally, force-push the updated, single-commit branch:

```bash
git push --force-with-lease
```

### 6.2 Squash via GitHub UI (simple, but last-minute)

1. In the PR, click **"Merge" → "Squash and merge."**
2. Tweak the commit title/description as needed.
3. Ensure the `Signed-off-by:` trailer is present (GitHub adds it automatically if you enabled DCO in the repo).

Use the UI method only if reviewers are done-every push re-triggers CI.

---

## 7. Functional & Code Review Checklist

| Check                          | Why it matters                                  |
| ------------------------------ | ----------------------------------------------- |
| **Does it build locally?**     | Fastest signal that the code even compiles.     |
| **Does it build in Docker?**   | Catches missing OS packages or env-var mishaps. |
| **Unit tests green?**          | Ensures regressions are caught immediately.     |
| **No new lint errors?**        | Keeps the CI pipeline and codebase clean.       |
| **Commits squashed & signed?** | One commit history + DCO compliance.            |
| **Docs / comments updated?**   | Future devs will thank you.                     |

---

## 8. Merging the PR

* **Squash-and-merge** is the default merge strategy.
* Confirm the final commit message follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and retains a `Signed-off-by:` trailer.
* GitHub automatically deletes the source branch after a successful merge-no manual cleanup required.

**Verify GitHub CI status checks**

Before requesting review, confirm that **all** required status checks on the PR page are green ✅ ("All checks have passed"). You should now see something like:

```text
Secure Docker Build / docker-image              ✅  Successful in ~4m
Build Python Package / python-package (3.11)    ✅  Successful in ~2m
Tests & Coverage / pytest                       ✅  Successful in ~3m
Lint & Static Analysis / lint                   ✅  Successful in ~2m
Bandit / bandit                                 ✅  Successful in ~1m
CodeQL                                          ✅  Successful in ~1m
Dependency Review / dependency-review           ✅  Successful in seconds
DCO                                             ✅  Passed
```

If anything is red or still running, wait or push a **fix in the same PR** until every line is green. Ensure that a CODEOWNER is assigned to review the PR.

Once the PR is merged, double-check that the CI/CD pipeline deploys the change to all environments without errors.

If **any** of the above steps fail after the PR is merged or cannot deploy, leave a review requesting fixes and paste the relevant logs inline or as a gist.

---

## 9. Cleaning Up Locally
After the PR is merged:

* Switch back to the main branch
* Delete the local feature branch
* Prune deleted remote branches
```bash
git switch main
git branch -D pr-29                # or the feature branch name (replace pr-29 with your branch name)
git fetch -p                       # prune remotes that GitHub deleted
```
This removes references to remote branches that GitHub deleted after the merge.
This keeps your local environment clean and up to date.
---

## 10. Handy Git Aliases (Optional)

```bash
git config --global alias.co checkout
git config --global alias.cm 'commit -s -m'
git config --global alias.ca 'commit --amend -s'
git config --global alias.rb "rebase -i --autosquash"
git config --global alias.pr '!f() { git fetch upstream pull/$1/head:pr-$1 && git switch pr-$1; }; f'
```
Now you can run `git pr 42` to fetch-and-switch to PR #42 in one go.
These aliases are optional, but they save time and make Git commands easier to type.

---

## 11. Troubleshooting FAQ

| Symptom                  | Fix                                                                    |
| ------------------------ | ---------------------------------------------------------------------- |
| `error: cannot lock ref` | Run `git gc --prune=now` and retry.                                    |
| `docker: no space left`  | `docker system prune -af && docker volume prune`                       |
| Unit tests hang on macOS | Ensure you aren't on an Apple-Silicon image that needs platform flags. |

---

### Happy hacking! 🛠️

Submit improvements to this doc via another signed, squashed PR so everyone benefits.
