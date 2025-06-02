# ☁️ Deploying MCP Gateway on Google Cloud Run

MCP Gateway can be deployed to [Google Cloud Run](https://cloud.google.com/run), a fully managed, autoscaling platform for containerized applications. This guide provides step-by-step instructions to provision PostgreSQL and Redis backends, deploy the container, configure environment variables, authenticate using JWT, and monitor logs—all optimized for cost-efficiency.

---

## ✅ Overview

Google Cloud Run is an ideal platform for MCP Gateway due to its:

* **Serverless and cost-efficient** model with scale-to-zero capability.
* **Public HTTPS endpoints** with automatic TLS configuration.
* Seamless integration with **Cloud SQL (PostgreSQL)** and **Memorystore (Redis)**.
* Compatibility with public container registries like GitHub's `ghcr.io`.

You can deploy the public image directly:

```text
ghcr.io/ibm/mcp-context-forge:latest
```

---

## 🛠 Prerequisites

### 1. Install and Initialize Google Cloud CLI (`gcloud`)

Install the Google Cloud SDK:

* **macOS (Homebrew):**

  ```bash
  brew install --cask google-cloud-sdk
  ```

* **Debian/Ubuntu:**

  ```bash
  sudo apt-get install google-cloud-cli
  ```

* **Windows (PowerShell):**

  ```powershell
  winget install --id Google.CloudSDK
  ```

After installation, initialize the CLI:

```bash
gcloud init
```

Authenticate with your Google Cloud account:

```bash
gcloud auth login
```

### 2. Enable Required APIs

Enable the necessary Google Cloud APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com
```

### 3. Install Docker

Ensure Docker is installed for local testing and JWT token generation. Visit [Docker's official website](https://www.docker.com/get-started/) for installation instructions.

### 4. Set Environment Variables

Prepare the following environment variables:

| Variable              | Description                                           |
| --------------------- | ----------------------------------------------------- |
| `JWT_SECRET_KEY`      | Secret key for signing JWT tokens                     |
| `BASIC_AUTH_USER`     | Username for HTTP Basic Authentication                |
| `BASIC_AUTH_PASSWORD` | Password for HTTP Basic Authentication                |
| `AUTH_REQUIRED`       | Set to `true` to enforce authentication               |
| `DATABASE_URL`        | PostgreSQL connection string                          |
| `REDIS_URL`           | Redis connection string                               |
| `CACHE_TYPE`          | Set to `redis` for production environments            |
| `PORT`                | Port number the application listens on (e.g., `4444`) |

---

## ⚙️ Setup Steps

### 1. Provision Cloud SQL (PostgreSQL)

Create a PostgreSQL instance using the `db-f1-micro` tier for cost efficiency:

```bash
gcloud sql instances create mcpgw-db \
  --database-version=POSTGRES_17 \
  --tier=db-f1-micro \
  --region=us-central1
```

Set the password for the `postgres` user:

```bash
gcloud sql users set-password postgres \
  --instance=mcpgw-db \
  --password=mysecretpassword
```

Create the `mcpgw` database:

```bash
gcloud sql databases create mcpgw --instance=mcpgw-db
```

Retrieve the IP address of the instance:

```bash
gcloud sql instances describe mcpgw-db \
  --format="value(ipAddresses.ipAddress)"
```

> **Note:** The `db-f1-micro` tier is a shared-core instance designed for low-cost development and testing environments. It is not covered by the Cloud SQL SLA.

### 2. Provision Memorystore (Redis)

Create a Redis instance using the Basic Tier with 1 GiB capacity:

```bash
gcloud redis instances create mcpgw-redis \
  --region=us-central1 \
  --tier=BASIC \
  --size=1
```

Retrieve the host IP address:

```bash
gcloud redis instances describe mcpgw-redis \
  --region=us-central1 \
  --format="value(host)"
```

> **Note:** The Basic Tier provides a standalone Redis instance suitable for applications that can tolerate potential data loss during failures.

### 3. Deploy to Google Cloud Run

Deploy the MCP Gateway container with minimal resource allocation:

```bash
gcloud run deploy mcpgateway \
  --image=ghcr.io/ibm/mcp-context-forge:latest \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --port=4444 \
  --cpu=1 \
  --memory=256Mi \
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

> **Replace `<SQL_IP>` and `<REDIS_IP>`** with the actual IP addresses obtained from the previous steps.

---

## 🔒 Authentication and Access

### Generate a JWT Bearer Token

Use the MCP Gateway container to generate a JWT token:

```bash
docker run -it --rm ghcr.io/ibm/mcp-context-forge:latest \
  python3 -m mcpgateway.utils.create_jwt_token -u admin
```

Export the token as an environment variable:

```bash
export MCPGATEWAY_BEARER_TOKEN=<paste-token-here>
```

### Perform Smoke Tests

Test the `/health` and `/tools` endpoints:

```bash
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/health

curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/tools
```

> **Replace `<your-cloud-run-url>`** with the URL provided after deploying the service.

---

## 📊 Logs and Monitoring

### View Logs via CLI

Tail real-time logs:

```bash
gcloud run services logs tail mcpgateway --region us-central1
```

Read recent logs:

```bash
gcloud run services logs read mcpgateway --limit 50
```

Filter logs by severity:

```bash
gcloud run services logs read mcpgateway --severity=ERROR
```

### Access Logs via Console

Navigate to the [Cloud Run Console](https://console.cloud.google.com/run) and select your service to view logs and metrics.

---

## 📦 GitHub Actions Deployment (Optional)

Automate builds and deployments using GitHub Actions. Refer to the workflow file:

```
.github/workflows/google-cloud-run.yml
```

This workflow:

* Restores and updates a local BuildKit layer cache.
* Builds the Docker image from `Containerfile.lite`.
* Pushes the image to Google Artifact Registry.
* Deploys to Google Cloud Run with `--max-instances=1`.

---

## 📘 Notes and Tips

* **HTTPS by Default:** Cloud Run services are accessible over HTTPS without additional configuration.

* **Custom Domains:** You can map custom domains via the Cloud Run settings.

* **Secret Management:** Consider using [Secret Manager](https://cloud.google.com/secret-manager) for managing sensitive environment variables.

* **Cold Starts:** To reduce cold start latency, set a minimum number of instances:

  ```bash
  --min-instances=1
  ```

* **Monitoring:** Utilize [Cloud Monitoring](https://cloud.google.com/monitoring) for detailed metrics and alerts.

---

## 🧩 Feature Summary

| Feature                | Supported |
| ---------------------- | --------- |
| HTTPS (built-in)       | ✅        |
| Custom domains         | ✅        |
| PostgreSQL (Cloud SQL) | ✅        |
| Redis (Memorystore)    | ✅        |
| Auto-scaling           | ✅        |
| Scale-to-zero          | ✅        |
| Max instance limit     | ✅        |

---

## 🧠 Additional Resources

* [Cloud Run Documentation](https://cloud.google.com/run/docs)
* [Cloud SQL for PostgreSQL Documentation](https://cloud.google.com/sql/docs/postgres)
* [Memorystore for Redis Documentation](https://cloud.google.com/memorystore/docs/redis)
* [Google Cloud SDK Installation Guide](https://cloud.google.com/sdk/docs/install)
* [Cloud Run Pricing](https://cloud.google.com/run/pricing)
* [Cloud SQL Pricing](https://cloud.google.com/sql/pricing)
* [Memorystore Pricing](https://cloud.google.com/memorystore/docs/redis/pricing)

---

By following this guide, you can deploy MCP Gateway on Google Cloud Run using the most cost-effective configurations, ensuring efficient resource utilization and seamless scalability.
