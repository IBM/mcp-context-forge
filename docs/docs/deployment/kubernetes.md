# ☸️ Kubernetes / OpenShift Deployment

You can deploy MCP Gateway to any K8s-compliant platform — including vanilla Kubernetes, OpenShift, and managed clouds like GKE, AKS, and EKS.

---

## 🚀 Quick Start with Manifest (YAML)

A basic Kubernetes deployment might look like:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcpgateway
  template:
    metadata:
      labels:
        app: mcpgateway
    spec:
      containers:
        - name: gateway
          image: ghcr.io/YOUR_ORG/mcpgateway:latest
          ports:
            - containerPort: 4444
          envFrom:
            - configMapRef:
                name: mcpgateway-env
          volumeMounts:
            - mountPath: /app/.env
              name: env-volume
              subPath: .env
      volumes:
        - name: env-volume
          configMap:
            name: mcpgateway-env
---
apiVersion: v1
kind: Service
metadata:
  name: mcpgateway
spec:
  selector:
    app: mcpgateway
  ports:
    - port: 80
      targetPort: 4444
```

> Replace `ghcr.io/YOUR_ORG/mcpgateway` with your built image.

---

## 🔐 TLS & Ingress

You can add:

* Cert-manager with TLS secrets
* An Ingress resource that routes to `/admin`, `/tools`, etc.

Example Ingress snippet:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcpgateway
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  rules:
    - host: gateway.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mcpgateway
                port:
                  number: 80
  tls:
    - hosts:
        - gateway.example.com
      secretName: mcpgateway-tls
```

---

## 📦 Configuration via ConfigMap

You can load your `.env` as a ConfigMap:

```bash
kubectl create configmap mcpgateway-env --from-env-file=.env
```

> Make sure it includes `JWT_SECRET_KEY`, `AUTH_REQUIRED`, etc.

---

## 💡 OpenShift Considerations

* Use `Route` instead of Ingress
* You may need to run the container as an unprivileged user
* Set `SECURITY_CONTEXT_RUNASUSER` if needed

---

## 🧪 Health Check Probes

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 4444
  initialDelaySeconds: 10
  periodSeconds: 15
```

---
