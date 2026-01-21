# ☁️ Deploying MCP Gateway on Google Cloud Run

MCP Gateway can be deployed to [Google Cloud Run](https://cloud.google.com/run), a fully managed, autoscaling platform for containerized applications. This guide provides step-by-step instructions to provision PostgreSQL and Redis backends, deploy the container, configure environment variables, authenticate using JWT, and monitor logs-all optimized for cost-efficiency.

---

## ✅ Overview

Google Cloud Run is an ideal platform for MCP Gateway due to its:

* **Serverless and cost-efficient** model with scale-to-zero capability.
* **Public HTTPS endpoints** with automatic TLS configuration.
* Seamless integration with **Cloud SQL (PostgreSQL)** and **Memorystore (Redis)**.
* Compatibility with public container registries like GitHub's `ghcr.io`.

You can deploy the public image directly:

```text
ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2
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

> These steps also apply to WSL2 running Ubuntu.

  ```bash
  # Update package lists and install necessary utilities
  sudo apt-get update
  sudo apt-get install -y apt-transport-https ca-certificates gnupg curl

  # Import the Google Cloud public key securely
  # This is for newer distributions (Debian 9+ or Ubuntu 18.04+).
  curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

  # Add the Google Cloud SDK distribution URI as a package source
  # This is for newer distributions, ensuring packages are signed by the key we just added.
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list

  # Update your package lists again to recognize the new repository
  sudo apt-get update

  # Install the Google Cloud CLI
  sudo apt-get install -y google-cloud-cli
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

Set a project ID:

```bash
gcloud config set project PROJECT_ID
```

### 2. Enable Required APIs

Enable the necessary Google Cloud APIs:

```bash
# This might take a minute..
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

Consider creating a `.env.gcr` file where you will record the various settings used during deployment.

```bash
# ─── Google Cloud project ───────────────────────────────────
PROJECT_ID=
REGION=us-central1
SERVICE_NAME=mcpgateway

# ─── Authentication ─────────────────────────────────────────
JWT_SECRET_KEY=
BASIC_AUTH_USER=
BASIC_AUTH_PASSWORD=
AUTH_REQUIRED=true

# ─── Cloud SQL (PostgreSQL) ─────────────────────────────────
SQL_INSTANCE=mcpgw-db
SQL_REGION=us-central1
DATABASE_URL=postgresql+psycopg://postgres:<PASSWORD>@<SQL_IP>:5432/mcpgw

# ─── Memorystore (Redis) ────────────────────────────────────
REDIS_INSTANCE=mcpgw-redis
REDIS_REGION=us-central1
REDIS_URL=redis://<REDIS_IP>:6379/0
CACHE_TYPE=redis

# ─── Application ────────────────────────────────────────────
PORT=4444
```

---

## ⚙️ Setup Steps

### 1. Provision Cloud SQL (PostgreSQL)

Create a PostgreSQL instance using the `db-f1-micro` tier for cost efficiency:

```bash
# POSTGRES_16 and POSTGRES_17 default to Enterprise Plus; adding --edition=ENTERPRISE lets you pick db-f1-micro
gcloud sql instances create mcpgw-db \
  --database-version=POSTGRES_17 \
  --edition=ENTERPRISE \
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

Cloud Run only accepts container images that live in Artifact Registry or the older Container Registry endpoints; anything pulled from the public internet (for example ghcr.io) must first be proxied or copied into Artifact Registry.


#### Set Your Project ID

Begin by setting your Google Cloud project ID as an environment variable:

```bash
export PROJECT_ID="your-project-id"
```

Replace `"your-project-id"` with your actual Google Cloud project ID.

#### Enable Required APIs

Ensure that the necessary Google Cloud APIs are enabled:

```bash
gcloud services enable artifactregistry.googleapis.com
```

#### Create a Remote Repository

Set up a remote repository in Artifact Registry that proxies GitHub Container Registry (GHCR):

```bash
gcloud artifacts repositories create ghcr-remote \
  --project=$PROJECT_ID \
  --repository-format=docker \
  --location=us-central1 \
  --description="Proxy for GitHub Container Registry" \
  --mode=remote-repository \
  --remote-docker-repo=https://ghcr.io
```

#### Retrieve Cloud SQL Instance Connection Name

```bash
gcloud sql instances describe mcpgw-db \
  --format="value(connectionName)"
```

It will output something like this:

```
your-project-id:us-central1:mcpgw-db
```


#### Allow ingress to your database.

Consider only allowing the Cloud Run IP range.

```bash
gcloud sql instances patch mcpgw-db \
  --authorized-networks=0.0.0.0/0
```

#### Deploy the MCP Gateway container with minimal resource allocation:

```bash
gcloud run deploy mcpgateway \
  --image=us-central1-docker.pkg.dev/$PROJECT_ID/ghcr-remote/ibm/mcp-context-forge:latest
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --port=4444 \
  --cpu=1 \
  --memory=512i \
  --max-instances=1 \
  --set-env-vars=\
JWT_SECRET_KEY=jwt-secret-key,\
BASIC_AUTH_USER=admin,\
BASIC_AUTH_PASSWORD=changeme,\
AUTH_REQUIRED=true,\
DATABASE_URL=postgresql+psycopg://postgres:mysecretpassword@<SQL_IP>:5432/mcpgw,\
REDIS_URL=redis://<REDIS_IP>:6379/0,\
CACHE_TYPE=redis,\
HOST=0.0.0.0,\
GUNICORN_WORKERS=1
```

> **Replace `<SQL_IP>` and `<REDIS_IP>`** with the actual IP addresses obtained from the previous steps.
> Do not leave out the HOST=0.0.0.0 to ensure the container listens on all ports, or the container engine won't be able to reach the container.
> Setting the number of GUNICORN_WORKERS lets you control how much memory the service consumes.

#### Check the logs

```bash
gcloud run services logs read mcpgateway --region=us-central1
```
---

#### Check that the database is created:

You can use any PostgreSQL client, such as `psql`. You should see the list of tables when using `dt;`

```bash
psql postgresql+psycopg://postgres:mysecretpassword@<SQL_IP>:5432/mcpgw

mcpgw=> \dt;
                    List of relations
 Schema |             Name             | Type  |  Owner
--------+------------------------------+-------+----------
 public | gateways                     | table | postgres
 public | mcp_messages                 | table | postgres
 public | mcp_sessions                 | table | postgres
 public | prompt_gateway_association   | table | postgres
 public | prompt_metrics               | table | postgres
 public | prompts                      | table | postgres
 public | resource_gateway_association | table | postgres
 public | resource_metrics             | table | postgres
 public | resource_subscriptions       | table | postgres
 public | resources                    | table | postgres
 public | server_metrics               | table | postgres
 public | server_prompt_association    | table | postgres
 public | server_resource_association  | table | postgres
 public | server_tool_association      | table | postgres
 public | servers                      | table | postgres
 public | tool_gateway_association     | table | postgres
 public | tool_metrics                 | table | postgres
 public | tools                        | table | postgres
(18 rows)
```

## 🔒 Authentication and Access

### Generate a JWT Bearer Token

Use the MCP Gateway container to generate a JWT token:

```bash
docker run -it --rm ghcr.io/ibm/mcp-context-forge:1.0.0-BETA-2 \
  python3 -m mcpgateway.utils.create_jwt_token -u admin@example.com --secret jwt-secret-key
```

Export the token as an environment variable:

```bash
export MCPGATEWAY_BEARER_TOKEN=<paste-token-here>
```

### Perform Smoke Tests

Test the `/health`, `/version`, and `/tools` endpoints:

```bash
# Check that the service is healthy
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/health

# Check that version reports the version and show Postgres/Redis as connected
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/health

# Check that tools return an empty list []
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     https://<your-cloud-run-url>/tools
```

> **Replace `<your-cloud-run-url>`** with the URL provided after deploying the service.

---

## 📊 Logs and Monitoring

### View Logs via CLI

Tailing real-time logs requires `google-cloud-cli-log-streaming`. Ex: `sudo apt-get install google-cloud-cli-log-streaming`:

```bash
gcloud beta run services logs tail mcpgateway --region=us-central1
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

### Setting up permissions for Google Cloud Run deployment

Instead of project-wide permissions, grant permissions on specific resources:

```bash
# Create service account
gcloud iam service-accounts create github-mcpgateway \
  --display-name="GitHub MCP Gateway Deploy"

# Grant permission ONLY on the specific Cloud Run service
gcloud run services add-iam-policy-binding mcpgateway \
  --region=us-central1 \
  --member="serviceAccount:github-mcpgateway@YOUR-PROJECT-ID.iam.gserviceaccount.com" \
  --role="roles/run.developer"

# Grant permission ONLY on the specific Artifact Registry repository
gcloud artifacts repositories add-iam-policy-binding mcpgateway \
  --location=us-central1 \
  --member="serviceAccount:github-mcpgateway@YOUR-PROJECT-ID.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# Create the key
gcloud iam service-accounts keys create restricted-key.json \
  --iam-account=github-mcpgateway@YOUR-PROJECT-ID.iam.gserviceaccount.com
```

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
