# 📚 Tutorials

> Step-by-step guides to help you deploy and integrate ContextForge and related components using both **cloud-native** and **local containerized** environments.

---

## 🚀 Cloud Deployment with Argo CD and IBM Cloud Kubernetes Service

This guide walks you through deploying the **ContextForge Stack** on **IBM Cloud Kubernetes Service (IKS)** using **Helm** and **Argo CD** for GitOps-based lifecycle management. You'll learn how to:

- Build and push container images to IBM Container Registry
- Provision an IKS cluster with VPC-native networking
- Deploy the full ContextForge Helm chart via Argo CD
- Configure services like PostgreSQL, Redis, and TLS
- Connect AI clients like VS Code Copilot and LangChain Agent

👉 [Read the full guide](argocd-helm-deployment-ibm-cloud-iks.md)

---

## 🧠 Local Deployment of OpenWebUI + MCP Tools

This tutorial helps you set up **OpenWebUI** integrated with **Ollama**, **LiteLLM**, **MCPO**, and the **ContextForge** in a local containerized environment using Docker. It covers:

- Running LLMs locally via Ollama
- Using LiteLLM as a proxy for unified model access
- Bridging MCP tools through MCPO to OpenWebUI
- Managing MCP servers with the ContextForge
- Connecting it all through Docker networks

Perfect for experimenting on your workstation or air-gapped environments.

👉 [View the tutorial](openwebui-tutorial.md)

---


## 📦 Additional Resources

- [ContextForge GitHub](https://github.com/ibm/mcp-context-forge)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [OpenWebUI Documentation](https://docs.openwebui.com/)

Stay tuned for more guides on CI/CD, hybrid federation, observability, and secure API operations.
