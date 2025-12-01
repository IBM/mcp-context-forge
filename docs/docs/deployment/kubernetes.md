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
    # Create .env file for HMAC (development/simple deployments)
    cat > .env << EOF
    HOST=0.0.0.0
    PORT=4444
    DATABASE_URL=sqlite:///./mcp.db
    JWT_ALGORITHM=HS256
    JWT_SECRET_KEY=your-strong-secret-key-here
    BASIC_AUTH_USER=admin
    BASIC_AUTH_PASSWORD=changeme
    MCPGATEWAY_UI_ENABLED=true
    MCPGATEWAY_ADMIN_API_ENABLED=true
    EOF

    kubectl create configmap mcpgateway-env --from-env-file=.env

    # For production with asymmetric JWT (RSA/ECDSA)
    # 1. Generate keys locally:
    #    mkdir jwt && openssl genrsa -out jwt/private.pem 4096
    #    openssl rsa -in jwt/private.pem -pubout -out jwt/public.pem
    #
    # 2. Create secret for JWT keys:
    #    kubectl create secret generic jwt-keys \
    #      --from-file=private.pem=jwt/private.pem \
    #      --from-file=public.pem=jwt/public.pem
    #
    # 3. Update environment configuration:
    #    JWT_ALGORITHM=RS256
    #    JWT_PUBLIC_KEY_PATH=/etc/jwt/public.pem
    #    JWT_PRIVATE_KEY_PATH=/etc/jwt/private.pem
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

---

## 🔐 Production Deployment with Asymmetric JWT

For enterprise production deployments, use asymmetric JWT with proper secret management:

### Step 1: Generate and Store JWT Keys

```bash
# Option 1: Use Makefile (Recommended)
make certs-jwt                   # Generates certs/jwt/{private,public}.pem

# Create Kubernetes secret for JWT keys
kubectl create secret generic jwt-keys \
  --from-file=private.pem=certs/jwt/private.pem \
  --from-file=public.pem=certs/jwt/public.pem

# Option 2: Manual generation (Alternative)
mkdir -p certs/jwt
openssl genrsa -out certs/jwt/private.pem 4096
openssl rsa -in certs/jwt/private.pem -pubout -out certs/jwt/public.pem
kubectl create secret generic jwt-keys \
  --from-file=private.pem=certs/jwt/private.pem \
  --from-file=public.pem=certs/jwt/public.pem

# Note: Keep local keys for development, they're in .gitignore
```

### Step 2: Production ConfigMap with Asymmetric JWT

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcpgateway-config-prod
data:
  HOST: "0.0.0.0"
  PORT: "4444"
  DATABASE_URL: "mysql+pymysql://mysql:changeme@mysql-service:3306/mcp"

  # Asymmetric JWT Configuration
  JWT_ALGORITHM: "RS256"
  JWT_PUBLIC_KEY_PATH: "/etc/jwt/public.pem"
  JWT_PRIVATE_KEY_PATH: "/etc/jwt/private.pem"
  JWT_AUDIENCE: "mcpgateway-production"
  JWT_ISSUER: "your-organization"
  JWT_AUDIENCE_VERIFICATION: "true"
  REQUIRE_TOKEN_EXPIRATION: "true"

  # Security settings
  ENVIRONMENT: "production"
  MCPGATEWAY_UI_ENABLED: "false"        # Disable for production
  MCPGATEWAY_ADMIN_API_ENABLED: "false" # Disable for production
  BASIC_AUTH_USER: "admin"
  BASIC_AUTH_PASSWORD: "changeme"
```

### Step 3: Production Deployment with JWT Keys

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcpgateway-prod
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcpgateway-prod
  template:
    metadata:
      labels:
        app: mcpgateway-prod
    spec:
      containers:

        - name: mcpgateway
          image: ghcr.io/ibm/mcp-context-forge:latest
          ports:

            - containerPort: 4444
          envFrom:

            - configMapRef:
                name: mcpgateway-config-prod
          volumeMounts:
            # Mount JWT keys as read-only
            - name: jwt-keys
              mountPath: /etc/jwt
              readOnly: true
          securityContext:
            runAsNonRoot: true
            runAsUser: 1001
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
          resources:
            requests:
              memory: "256Mi"
              cpu: "200m"
            limits:
              memory: "512Mi"
              cpu: "500m"
      volumes:

        - name: jwt-keys
          secret:
            secretName: jwt-keys
            defaultMode: 0600
---
apiVersion: v1
kind: Service
metadata:
  name: mcpgateway-prod-service
spec:
  selector:
    app: mcpgateway-prod
  ports:

    - name: http
      port: 80
      targetPort: 4444
  type: ClusterIP
```

### Step 4: Security Considerations

**Key Rotation Strategy:**
```bash
# 1. Generate new key pair
openssl genrsa -out jwt/private_new.pem 4096
openssl rsa -in jwt/private_new.pem -pubout -out jwt/public_new.pem

# 2. Update secret with new keys
kubectl create secret generic jwt-keys-new \
  --from-file=private.pem=jwt/private_new.pem \
  --from-file=public.pem=jwt/public_new.pem

# 3. Update deployment to use new secret
kubectl patch deployment mcpgateway-prod \
  -p '{"spec":{"template":{"spec":{"volumes":[{"name":"jwt-keys","secret":{"secretName":"jwt-keys-new"}}]}}}}'

# 4. Clean up old secret after rollout
kubectl delete secret jwt-keys
```

**RBAC for JWT Keys:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: mcpgateway-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jwt-key-reader
rules:

  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["jwt-keys"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: mcpgateway-jwt-access
subjects:

  - kind: ServiceAccount
    name: mcpgateway-sa
roleRef:
  kind: Role
  name: jwt-key-reader
  apiGroup: rbac.authorization.k8s.io
```

!!! info "MariaDB & MySQL Kubernetes Support"
    MariaDB and MySQL are **fully supported** in Kubernetes deployments:

    - **36+ database tables** work perfectly with MariaDB 10.6+ and MySQL 8.0+
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
