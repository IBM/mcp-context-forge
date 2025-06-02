# ☁️ Google Cloud Run

MCP Gateway can be deployed to [Google Cloud Run](https://cloud.google.com/run), a fully managed, autoscaling platform for containers with built-in HTTPS, identity, and integration with other GCP services like Cloud SQL and Memorystore.

This guide walks through provisioning a PostgreSQL and Redis backend, deploying the container, injecting secrets, and verifying access using JWT.

---

## ✅ Overview

Cloud Run is ideal for MCP Gateway use cases:

- **Serverless and cost-efficient** (scale to zero)
- **Public HTTPS endpoints** with zero config
- Built-in **integration with Cloud SQL (PostgreSQL)** and **Memorystore (Redis)**
- Compatible with public container registries like GitHub’s `ghcr.io`

You can deploy the public image directly:

```text
ghcr.io/ibm/mcp-context-forge:latest
````

---

## 🛠 Prerequisites

* Google Cloud project with billing enabled

* `gcloud` CLI authenticated (`gcloud init`)

* Enabled APIs:

  ```bash
  gcloud services enable run.googleapis.com sqladmin.googleapis.com redis.googleapis.com
  ```

* Docker (for local testing or JWT token generation)

* `.env` values for:

  * `JWT_SECRET_KEY`
  * `DATABASE_URL`
  * `REDIS_URL`
  * `AUTH_REQUIRED`, `BASIC_AUTH_USER`, etc.

---

## ⚙️ Setup Steps

### 1. 🗄️ Provision Cloud SQL (PostgreSQL)

```bash
gcloud sql instances create mcpgw-db \
  --database-version=POSTGRES_14 \
  --cpu=2 --memory=4GiB \
  --region=us-central1

gcloud sql users set-password postgres \
  --instance=mcpgw-db --password=mysecretpassword

gcloud sql databases create mcpgw --instance=mcpgw-db
```

Find the IP address:

```bash
gcloud sql instances describe mcpgw-db \
  --format="value(ipAddresses.ipAddress)"
```

---

### 2. ⚡ Provision Memorystore (Redis)

```bash
gcloud redis instances create mcpgw-redis \
  --region=us-central1 \
  --tier=STANDARD_HA \
  --size=1
```

Get the Redis IP:

```bash
gcloud redis instances describe mcpgw-redis \
  --region=us-central1 \
  --format="value(host)"
```

---

### 3. 🚀 Deploy to Google Cloud Run

```bash
gcloud run deploy mcpgateway \
  --image=ghcr.io/ibm/mcp-context-forge:latest \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --port=4444 \
  --cpu=2 \
  --memory=2Gi \
  --max-instances=1 \
  --set-env-vars=\
JWT_SECRET_KEY=your-secret,\
BASIC_AUTH_USER=admin,\
BASIC_AUTH_PASSWORD=changeme,\
AUTH_REQUIRED=true,\
DATABASE_URL=postgresql://postgres:mysecretpassword@<SQL_IP>:5432/mcpgw,\
REDIS_URL=redis://<REDIS_IP>:6379/0,\
CACHE_TYPE=redis
```

> 🔐 Be sure to replace `<SQL_IP>` and `<REDIS_IP>` with the actual addresses you retrieved.

---

## 🔒 Auth & Access

### Generate a Bearer Token

You can use the official container to generate a token:

```bash
docker run -it --rm ghcr.io/ibm/mcp-context-forge:latest \
  python3 -m mcpgateway.utils.create_jwt_token -u admin
```

Export it:

```bash
export MCPGATEWAY_BEARER_TOKEN=<paste-token-here>
```

### Smoke Test

```bash
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/health

curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/tools
```

---

## 📦 GitHub Actions Deployment (Optional)

You can automate builds and deployments using GitHub Actions. See:

```
.github/workflows/deploy-gcr.yml
```

It builds from `Containerfile.lite`, pushes to Artifact Registry, and deploys to Cloud Run with `--max-instances=1`.

---

## 📘 Notes & Tips

* Cloud Run endpoints are public HTTPS by default
* Add a custom domain via Cloud Run settings (optional)
* Use Secret Manager or env vars for sensitive values
* To avoid cold starts, you can enable **minimum instance = 1**
* Logs and metrics available via Cloud Console

---

## 🧩 Summary

| Feature              | Supported               |
| -------------------- | ----------------------- |
| HTTPS (built-in)     | ✅                      |
| Custom domains       | ✅                      |
| Postgres (Cloud SQL) | ✅                      |
| Redis (Memorystore)  | ✅                      |
| Auto-scaling         | ✅                      |
| Scale-to-zero        | ✅                      |
| Max instance limit   | ✅                      |

---

## 🧠 Resources

* [Cloud Run documentation](https://cloud.google.com/run/docs)
* [Cloud SQL connection tips](https://cloud.google.com/sql/docs/postgres/connect-run)
* [Memorystore overview](https://cloud.google.com/memorystore/docs/redis)
