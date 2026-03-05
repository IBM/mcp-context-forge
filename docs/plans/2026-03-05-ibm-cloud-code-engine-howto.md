# IBM Cloud Code Engine How-To Migration & Enhancement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `ibm-code-engine.md` from the deployment section to the howto section, enhance it with verification steps and troubleshooting, add a DRAFT banner, and leave a redirect note in the deployment section.

**Architecture:** Move the file, update three cross-reference locations (deployment/.pages, deployment/index.md, index.md), update howto nav, then enhance the moved file in-place with verification blocks after each major phase and a troubleshooting section at the bottom.

**Tech Stack:** MkDocs Material, awesome-pages, pymdownx.tabbed, admonitions

---

## Task 1: Move the file and update deployment nav

**Files:**
- Move: `docs/docs/deployment/ibm-code-engine.md` → `docs/docs/howto/ibm-cloud-code-engine.md`
- Modify: `docs/docs/deployment/.pages` — replace `ibm-code-engine.md` entry with redirect page
- Create: `docs/docs/deployment/ibm-code-engine.md` — redirect stub pointing to new location

**Step 1: Copy the file to its new location**

```bash
cp docs/docs/deployment/ibm-code-engine.md docs/docs/howto/ibm-cloud-code-engine.md
```

**Step 2: Replace the original with a redirect stub**

Replace the entire content of `docs/docs/deployment/ibm-code-engine.md` with a short redirect page:

```markdown
# IBM Code Engine

This guide has moved to the **How-To Guides** section.

**[Deploy ContextForge on IBM Cloud with Code Engine](../howto/ibm-cloud-code-engine.md)**
```

**Step 3: Verify both files exist**

Run: `ls docs/docs/deployment/ibm-code-engine.md docs/docs/howto/ibm-cloud-code-engine.md`
Expected: both files listed

**Step 4: Commit**

```bash
git add docs/docs/howto/ibm-cloud-code-engine.md docs/docs/deployment/ibm-code-engine.md
git commit -s -m "docs: move IBM Code Engine guide to howto section with redirect"
```

---

## Task 2: Update cross-references

**Files:**
- Modify: `docs/docs/deployment/index.md:31` — update table link to point to howto
- Modify: `docs/docs/index.md:575` — update table link to point to howto
- Modify: `docs/docs/howto/.pages` — add `ibm-cloud-code-engine.md`
- Modify: `docs/docs/howto/index.md` — add bullet for the new guide

**Step 1: Update deployment/index.md table row**

Change:
```
| [IBM Code Engine](ibm-code-engine.md) | Serverless container build & run on IBM Cloud                                             |
```
To:
```
| [IBM Code Engine](../howto/ibm-cloud-code-engine.md) | Serverless container build & run on IBM Cloud (moved to How-To Guides)                    |
```

**Step 2: Update docs/index.md table row**

Change:
```
| **IBM Cloud** | [Code Engine](deployment/ibm-code-engine.md) |
```
To:
```
| **IBM Cloud** | [Code Engine](howto/ibm-cloud-code-engine.md) |
```

**Step 3: Update howto/.pages**

Add `ibm-cloud-code-engine.md` to the nav list:
```yaml
nav:
  - index.md
  - rbac-tool-authorization.md
  - ibm-cloud-code-engine.md
```

**Step 4: Update howto/index.md**

Add a second bullet in the "Available Guides" section:
```markdown
- [Deploy ContextForge on IBM Cloud with Code Engine](ibm-cloud-code-engine.md) -- Provision Code Engine, Databases for PostgreSQL, and Databases for Redis for a production-ready deployment. **DRAFT**
```

**Step 5: Verify all links resolve**

Run from `docs/docs/`:
```bash
# Check deployment redirect link
test -f howto/ibm-cloud-code-engine.md && echo "OK: howto target exists"
# Check deployment/index.md link
test -f howto/ibm-cloud-code-engine.md && echo "OK: deployment index link"
# Check docs/index.md link
test -f howto/ibm-cloud-code-engine.md && echo "OK: site index link"
```

**Step 6: Commit**

```bash
git add docs/docs/deployment/index.md docs/docs/index.md docs/docs/howto/.pages docs/docs/howto/index.md
git commit -s -m "docs: update cross-references for IBM Code Engine guide move"
```

---

## Task 3: Add DRAFT banner and verification steps

**Files:**
- Modify: `docs/docs/howto/ibm-cloud-code-engine.md`

This is the main enhancement task. Make the following edits to the moved file, verifying the existing content is correct as you go:

**Step 1: Add DRAFT banner and update title**

At the very top of the file, before the title, add:

```markdown
!!! warning "DRAFT"

    This guide is a draft and may contain inaccuracies. Verify all commands and configurations against current IBM Cloud documentation before use in production.
```

Update the title from `# ⚙️ IBM Code Engine` to `# Deploy ContextForge on IBM Cloud with Code Engine` (no emoji, matches how-to style).

**Step 2: Add verification after Section 2 (environment files)**

After the `.env.ce` block and before Section 3, add a verification block:

```markdown
### Verify environment files

```bash
# Confirm both env files exist and contain required keys
test -f .env && echo "OK: .env exists" || echo "MISSING: .env"
test -f .env.ce && echo "OK: .env.ce exists" || echo "MISSING: .env.ce"
grep -q DATABASE_URL .env && echo "OK: DATABASE_URL set" || echo "WARNING: DATABASE_URL not set in .env"
grep -q JWT_SECRET_KEY .env && echo "OK: JWT_SECRET_KEY set" || echo "WARNING: JWT_SECRET_KEY not set in .env"
```
```

**Step 3: Add verification after Section 4 / manual CLI step 5 (image push)**

After the `ibmcloud cr images` command in the manual workflow (after line ~181), add:

```markdown
### Verify image in registry

```bash
# Confirm the image is present in ICR
ibmcloud cr images --restrict "$(echo "$IBMCLOUD_IMAGE_NAME" | cut -d/ -f2)"
# Expected: your image listed with "No Issues" vulnerability status
```
```

**Step 4: Add verification after Section 4 / manual CLI step 7 (deploy)**

After the deploy/update block (after line ~203), add:

```markdown
### Verify application is running

```bash
# Check application status
ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" | grep -E "Status|URL|Ready"
# Expected: Status showing "Ready", URL showing the public endpoint

# Quick health check
APP_URL=$(ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" --output url)
curl -s "${APP_URL}/health" | jq .
# Expected: {"status": "ok"} or similar health response
```
```

**Step 5: Add verification after Section 7 step 5 (PostgreSQL secret mounted)**

After the `ibmcloud ce application update` command for PostgreSQL (after line ~292), add:

```markdown
### Verify PostgreSQL connectivity

```bash
# Confirm the secret is mounted
ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" | grep mcpgw-db-url
# Expected: secret listed in environment references

# Test the application can reach the database (wait ~30s for restart)
APP_URL=$(ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" --output url)
curl -s "${APP_URL}/health" | jq .
# Expected: health check passes — if it fails, check application logs:
# ibmcloud ce application logs --name "$IBMCLOUD_CODE_ENGINE_APP" --tail 50
```
```

**Step 6: Add verification after Section 8 step 5 (Redis secret mounted)**

After the `ibmcloud ce application update` command for Redis (after line ~372), add:

```markdown
### Verify Redis connectivity

```bash
# Confirm both secrets are mounted
ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" | grep -E "mcpgw-(db|redis)"
# Expected: both mcpgw-db-url and mcpgw-redis-url listed

# Verify the application restarts and is healthy
APP_URL=$(ibmcloud ce application get --name "$IBMCLOUD_CODE_ENGINE_APP" --output url)
curl -s "${APP_URL}/health" | jq .
# Expected: health check passes with Redis cache active
```
```

**Step 7: Commit verification steps**

```bash
git add docs/docs/howto/ibm-cloud-code-engine.md
git commit -s -m "docs: add DRAFT banner and verification steps to IBM Cloud guide"
```

---

## Task 4: Add troubleshooting section

**Files:**
- Modify: `docs/docs/howto/ibm-cloud-code-engine.md`

**Step 1: Add troubleshooting section before the end of the file**

After the gunicorn section (Section 9), add a new section:

```markdown
---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ibmcloud ce application get` shows "Failed" | Image pull error — wrong registry secret or image path | Verify `IBMCLOUD_IMAGE_NAME` matches the pushed image: `ibmcloud cr images` |
| Application starts then crashes (OOMKilled) | Insufficient memory for gunicorn workers | Increase `IBMCLOUD_MEMORY` in `.env.ce` or reduce `workers` in `gunicorn.config.py` |
| `connection refused` to PostgreSQL | Database not yet provisioned or wrong hostname | Verify with: `ibmcloud resource service-instance mcpgw-db` and check credentials JSON |
| `SSL: CERTIFICATE_VERIFY_FAILED` on database connection | Missing `sslmode=require` in `DATABASE_URL` | Ensure `DATABASE_URL` ends with `?sslmode=require` |
| Redis connection timeout | Security group or allowlist blocking Code Engine IPs | IBM Cloud Databases allowlist must include Code Engine's outbound IPs, or use private endpoints |
| Application starts but `/tools` returns `[]` | Database is empty — first deploy needs bootstrap | Access `/admin` to configure gateways and virtual servers, or use the API |
| `ibmcloud ce application logs` shows no output | Application scaled to zero — no instances running | Send a request to wake it: `curl $APP_URL/health` then retry logs |
| Slow cold starts (>10s) | Code Engine scales from zero by default | Set `--min-scale 1` to keep at least one instance warm |

!!! tip "Checking application logs"

    Most deployment issues are visible in the application logs. Use these commands to investigate:

    ```bash
    # Recent logs (last 50 lines)
    ibmcloud ce application logs --name "$IBMCLOUD_CODE_ENGINE_APP" --tail 50

    # Follow logs in real-time
    ibmcloud ce application logs --name "$IBMCLOUD_CODE_ENGINE_APP" --follow

    # System events (scheduling, scaling, image pull)
    ibmcloud ce application events --name "$IBMCLOUD_CODE_ENGINE_APP"
    ```
```

**Step 2: Commit**

```bash
git add docs/docs/howto/ibm-cloud-code-engine.md
git commit -s -m "docs: add troubleshooting section to IBM Cloud Code Engine guide"
```

---

## Task 5: Final verification

**Step 1: Verify all howto files exist**

Run: `find docs/docs/howto -type f | sort`
Expected:
```
docs/docs/howto/.pages
docs/docs/howto/ibm-cloud-code-engine.md
docs/docs/howto/index.md
docs/docs/howto/rbac-tool-authorization.md
```

**Step 2: Verify redirect stub exists**

Run: `head -5 docs/docs/deployment/ibm-code-engine.md`
Expected: redirect content pointing to howto

**Step 3: Verify all cross-reference links resolve**

```bash
cd docs/docs
# From deployment/index.md
test -f howto/ibm-cloud-code-engine.md && echo "OK"
# From howto/ibm-cloud-code-engine.md — no outbound doc links to verify (all external)
# From index.md
test -f howto/ibm-cloud-code-engine.md && echo "OK"
```

**Step 4: Verify DRAFT banner is present**

Run: `head -5 docs/docs/howto/ibm-cloud-code-engine.md`
Expected: `!!! warning "DRAFT"` admonition at top

**Step 5: Count lines to confirm enhancements added**

Run: `wc -l docs/docs/howto/ibm-cloud-code-engine.md`
Expected: ~530-570 lines (up from 459 original)

**Step 6: Review git log**

Run: `git log --oneline -5`
Expected: 4 commits from this plan (tasks 1-4)
