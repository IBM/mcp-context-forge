# Azure Deployment

MCP Gateway can be deployed on Azure in multiple ways:

- **Azure Container Apps** (serverless)
- **Azure App Service** (PaaS for containers)
- **Azure Kubernetes Service (AKS)** (fully managed K8s)

---

## 🚀 Option 1: Azure Container Apps (Recommended)

Azure Container Apps is ideal for lightweight container-based workloads.

### Steps

1. **Build and push your image to Azure Container Registry (ACR):**

```bash
az acr login --name yourregistry
docker tag mcpgateway yourregistry.azurecr.io/mcpgateway
docker push yourregistry.azurecr.io/mcpgateway
```

2. **Create the container app:**

```bash
az containerapp create \
  --name mcpgateway \
  --resource-group my-rg \
  --image yourregistry.azurecr.io/mcpgateway \
  --target-port 4444 \
  --environment my-container-env \
  --registry-server yourregistry.azurecr.io \
  --env-vars-from-secrets .env
```

> You can mount `.env` via Key Vault or inject environment variables directly.

---

## 🚀 Option 2: Azure App Service

1. Push your image to ACR
2. Create an App Service plan and container-based Web App
3. Set `PORT=4444` and other env vars in Configuration → Application settings
4. Map your custom domain (optional)

---

## 🚀 Option 3: Azure Kubernetes Service (AKS)

Use your existing [Kubernetes deployment](kubernetes.md) instructions, but deploy to AKS.

* Deploy with Helm or `kubectl`
* Use Azure Load Balancer or Application Gateway
* Store secrets in Azure Key Vault (optional)

---

## 🔐 Secrets & Config

Use Azure CLI to upload your `.env` values to App Config or Key Vault:

```bash
az keyvault secret set --vault-name my-kv --name JWT-SECRET --value "super-secret"
```

Then reference in App Service / Container App using environment variables.

---

## 📡 DNS & TLS

* Use Azure Front Door or Application Gateway to handle TLS
* Point your domain to the public IP or hostname of the service

Example:

```bash
gateway.example.com → mygateway.eastus.azurecontainerapps.io
```

---
