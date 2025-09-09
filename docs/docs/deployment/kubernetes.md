# ☸️ Kubernetes / OpenShift Deployment

You can deploy MCP Gateway to any K8s-compliant platform - including vanilla Kubernetes, OpenShift, and managed clouds like GKE, AKS, and EKS.

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

=== "With SQLite (Default)"
    ```bash
    # Create .env file
    cat > .env << EOF
    HOST=0.0.0.0
    PORT=4444
    DATABASE_URL=sqlite:///./mcp.db
    JWT_SECRET_KEY=your-secret-key
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    MCPGATEWAY_UI_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true
    EOF

    kubectl create configmap mcpgateway-env --from-env-file=.env
    ```

=== "With MariaDB"
    ```bash
    # Create .env file
    cat > .env << EOF
    HOST=0.0.0.0
    PORT=4444
    DATABASE_URL=mysql+pymysql://mysql:changeme@mariadb-service:3306/mcp
    JWT_SECRET_KEY=your-secret-key
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    MCPGATEWAY_UI_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true
    EOF

    kubectl create configmap mcpgateway-env --from-env-file=.env
    ```

=== "With MySQL"
    ```bash
    # Create .env file
    cat > .env << EOF
    HOST=0.0.0.0
    PORT=4444
    DATABASE_URL=mysql+pymysql://mysql:changeme@mysql-service:3306/mcp
    JWT_SECRET_KEY=your-secret-key
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    MCPGATEWAY_UI_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true
    EOF

    kubectl create configmap mcpgateway-env --from-env-file=.env
    ```

=== "With PostgreSQL"
    ```bash
    # Create .env file
    cat > .env << EOF
    HOST=0.0.0.0
    PORT=4444
    DATABASE_URL=postgresql://postgres:changeme@postgres-service:5432/mcp
    JWT_SECRET_KEY=your-secret-key
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    MCPGATEWAY_UI_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true
    EOF

    kubectl create configmap mcpgateway-env --from-env-file=.env
```

> Make sure it includes `JWT_SECRET_KEY`, `AUTH_REQUIRED`, etc.

---

## 🗄 Database Deployment Examples

### MySQL Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mysql
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
        - name: mysql
          image: mysql:8
          env:
            - name: MYSQL_ROOT_PASSWORD
              value: mysecretpassword
            - name: MYSQL_DATABASE
              value: mcp
            - name: MYSQL_USER
              value: mysql
            - name: MYSQL_PASSWORD
              value: changeme
          ports:
            - containerPort: 3306
          volumeMounts:
            - name: mysql-storage
              mountPath: /var/lib/mysql
      volumes:
        - name: mysql-storage
          persistentVolumeClaim:
            claimName: mysql-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: mysql-service
spec:
  selector:
    app: mysql
  ports:
    - port: 3306
      targetPort: 3306
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mysql-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

!!! info "MariaDB & MySQL Kubernetes Support"
    MariaDB and MySQL are **fully supported** in Kubernetes deployments:

    - **36+ database tables** work perfectly with MariaDB 12.0+ and MySQL 8.4+
    - All **VARCHAR length issues** resolved for MariaDB/MySQL compatibility
    - Use connection string: `mysql+pymysql://mysql:changeme@mariadb-service:3306/mcp`

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
