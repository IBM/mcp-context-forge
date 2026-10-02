# Deploy ContextForge on IBM Cloud Code Engine

Single instance, SQLite on the container disk, public image. No build, no registry.

!!! warning "Data is ephemeral"
    SQLite lives on the container disk. Every instance replacement starts from an empty database.

## 1 - Prerequisites

- IBM Cloud account and the [IBM Cloud CLI](https://cloud.ibm.com/docs/cli?topic=cli-getting-started).
- Code Engine plugin: `ibmcloud plugin install code-engine -f`
- Log in and pick a project:

```bash
ibmcloud login                  # or: ibmcloud login --apikey "$IBMCLOUD_API_KEY"
ibmcloud target -r us-south -g default   # any region and resource group works, just set one
ibmcloud ce project select --name my-project   # or: ibmcloud ce project create --name my-project
```

The commands below are region-independent. Use whichever region and resource group you have; every
later command runs against the targeted one.

## 2 - Prepare `.env`

```bash
cp .env.example .env
make init-secrets-patch-env
```

That replaces the `__REPLACE_ME__` placeholders with real secrets. Read back the admin login used to
bootstrap the first user:

```bash
grep -E '^(PLATFORM_ADMIN_EMAIL|PLATFORM_ADMIN_PASSWORD)=' .env
```

Change `PLATFORM_ADMIN_EMAIL` if you want. Both values are read at first start only.

Append the SQLite and port settings:

```bash
cat >> .env <<'EOF'
PORT=4444
DATABASE_URL=sqlite:////tmp/mcp.db
CACHE_TYPE=memory
EOF
```

`.env.example` already sets `HOST=0.0.0.0`, which Code Engine requires. Leave `APP_DOMAIN` alone for
now; step 4 points it at the generated app URL.

!!! note "Inline comments"
    `--from-env-file` drops lines like `KEY=value  # comment`. Find them with
    `grep -nE '^[A-Z_]+=.*[^#]+#' .env` and move the comment to its own line.

## 3 - Deploy

```bash
ibmcloud ce secret create --name cf-app-secrets --format generic --from-env-file .env

ibmcloud ce application create --name mcpgateway \
    --image ghcr.io/ibm/mcp-context-forge:v1.0.11 \
    --env-from-secret cf-app-secrets \
    --port 4444 --cpu 1 --memory 4G \
    --min-scale 1 --max-scale 1 \
    --request-timeout 600
```

`--min-scale 1 --max-scale 1` keeps exactly one instance, so one SQLite file serves every request.
`--request-timeout 600` is the Code Engine maximum, so long-lived SSE streams survive.

## 4 - Point `APP_DOMAIN` at the app

Code Engine generates the hostname, so this only works after the app exists:

```bash
APP_URL=$(ibmcloud ce application get --name mcpgateway --output url)
curl -s "$APP_URL/health"

sed -i.bak "s|^APP_DOMAIN=.*|APP_DOMAIN=$APP_URL|" .env
ibmcloud ce secret update --name cf-app-secrets --from-env-file .env
ibmcloud ce application update --name mcpgateway
```

`APP_DOMAIN` must hold the `https://` URL that `--output url` returns. The CSRF middleware rejects
any admin POST whose `Referer` does not match it, and virtual-server MCP URLs are built from it. The
`.env.example` default of `http://localhost:8080` makes admin login fail with 403.

## 5 - Access

Open `$APP_URL/admin` and log in with `PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`.

For API calls, mint a token with the same `JWT_SECRET_KEY` the app runs with:

```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    -u "$(grep -m1 '^PLATFORM_ADMIN_EMAIL=' .env | cut -d= -f2-)" \
    --secret "$(grep -m1 '^JWT_SECRET_KEY=' .env | cut -d= -f2-)")

curl -s -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" "$APP_URL/tools"
```

Logs: `ibmcloud ce application logs --name mcpgateway --follow`

## 6 - Update and clean up

```bash
ibmcloud ce secret update --name cf-app-secrets --from-env-file .env
ibmcloud ce application update --name mcpgateway       # required, a secret update alone does not restart

ibmcloud ce revision list --application mcpgateway     # every update adds one
ibmcloud ce revision delete --name mcpgateway-00001 -f # old revisions keep billing for min-scale 1

ibmcloud ce application delete --name mcpgateway -f
ibmcloud ce secret delete --name cf-app-secrets -f
```
