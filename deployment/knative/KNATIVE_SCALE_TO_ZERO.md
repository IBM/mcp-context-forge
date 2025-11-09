# Knative Scale-to-Zero Setup for mcpgateway

## Overview
This document describes the Knative Serving configuration that enables scale-to-zero functionality for the mcpgateway application on Kubernetes clusters (including OpenShift).

## Prerequisites

- Kubernetes cluster (1.28+) or OpenShift (4.12+)
- Knative Serving installed ([installation guide](https://knative.dev/docs/install/))
- kubectl or oc CLI configured

## Components

### 1. PostgreSQL Configuration
**File:** [`postgres-config.yaml`](postgres-config.yaml)
**Namespace:** `mcp-gateway`

ConfigMap containing PostgreSQL connection settings. **Important:** Update these values before deploying:
- `POSTGRES_HOST`: PostgreSQL service hostname
- `POSTGRES_PORT`: PostgreSQL port (default: 5432)
- `POSTGRES_DB`: Database name
- `POSTGRES_USER`: Database username
- `POSTGRES_PASSWORD`: Database password (use Kubernetes Secrets in production)

### 2. KnativeServing Custom Resource
**File:** [`knative-serving.yaml`](knative-serving.yaml)
**Namespace:** `knative-serving`

This resource configures the Knative Serving platform with:
- **Scale-to-zero enabled**: Pods automatically scale down to 0 when idle
- **30-second grace period**: Pods remain running for 30 seconds after the last request
- **High availability**: 1 replica for control plane components
- **Ingress configuration**: Commented out by default - configure based on your setup
- **Autoscaling parameters**:
  - Target concurrency: 100 requests per pod
  - Stable window: 60 seconds
  - Panic window: 6 seconds

**Note:** The ingress configuration is commented out. Uncomment and configure based on your ingress controller (Kourier, Istio, or Contour). OpenShift users don't need to configure this as it's handled automatically by the Serverless Operator.

### 3. Knative Service for mcpgateway
**File:** [`mcpgateway-knative-service.yaml`](mcpgateway-knative-service.yaml)
**Namespace:** `mcp-gateway`

This replaces the traditional Deployment with a Knative Service that includes:
- **Min scale: 0** - Allows scaling to zero pods
- **Max scale: 1** - Maximum of 1 pod under load (adjust as needed)
- **Container concurrency: 100** - Up to 100 concurrent requests per pod
- **Scale-to-zero retention: 30s** - Keeps pods alive for 30 seconds after traffic stops
- **Health checks**: Readiness and liveness probes for proper traffic routing
- **Database config**: References `postgres-config` ConfigMap for connection settings

## Deployment Steps

### 1. Install Knative Serving and Ingress Controller

**For vanilla Kubernetes:**
```bash
# Install Knative Serving
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.12.0/serving-crds.yaml
kubectl apply -f https://github.com/knative/serving/releases/download/knative-v1.12.0/serving-core.yaml

# Install Kourier (recommended lightweight ingress)
kubectl apply -f https://github.com/knative/net-kourier/releases/download/knative-v1.12.0/kourier.yaml

# Configure Knative to use Kourier
kubectl patch configmap/config-network \
  --namespace knative-serving \
  --type merge \
  --patch '{"data":{"ingress-class":"kourier.ingress.networking.knative.dev"}}'
```

**For OpenShift:**
```bash
# Install OpenShift Serverless Operator from OperatorHub
# Then create KnativeServing instance (ingress is auto-configured)
```

### 2. Create namespace
```bash
kubectl create namespace mcp-gateway
```

### 3. Deploy PostgreSQL configuration
```bash
# Edit postgres-config.yaml with your database credentials first!
kubectl apply -f postgres-config.yaml
```

**Security Note:** For production, use Kubernetes Secrets instead of ConfigMap:
```bash
kubectl create secret generic postgres-credentials \
  --from-literal=POSTGRES_PASSWORD=your-secure-password \
  -n mcp-gateway
```

Then update the Knative Service to reference the Secret instead of ConfigMap.

### 4. Deploy Knative Serving configuration (optional)
```bash
# This step is optional - only needed if you want to customize
# autoscaling parameters beyond defaults
kubectl apply -f knative-serving.yaml
```

**Note:** For vanilla Kubernetes, you may need to uncomment and configure the `ingress-class` setting in [`knative-serving.yaml`](knative-serving.yaml:48) to match your installed ingress controller.

### 5. Deploy the mcpgateway service
```bash
kubectl apply -f mcpgateway-knative-service.yaml
```

### 6. Verify deployment
```bash
# Check service status
kubectl get ksvc mcpgateway -n mcp-gateway

# Check revisions
kubectl get revision -n mcp-gateway

# Expected output when idle (scale-to-zero active):
# NAME               CONFIG NAME   GENERATION   READY   ACTUAL REPLICAS   DESIRED REPLICAS
# mcpgateway-00001   mcpgateway    1            True    0                 0
```

## Checking Status

```bash
# For OpenShift:
$ oc get ksvc mcpgateway -n mcp-gateway

# For vanilla Kubernetes:
$ kubectl get ksvc mcpgateway -n mcp-gateway

# Check revisions:
$ kubectl get revision -n mcp-gateway
NAME               CONFIG NAME   GENERATION   READY   ACTUAL REPLICAS   DESIRED REPLICAS
mcpgateway-00001   mcpgateway    1            True    0                 0
```

✅ **Scale-to-zero is active**: The service shows 0 actual and 0 desired replicas when idle.

## How It Works

1. **Idle State**: When no traffic is received, Knative scales the pods to 0 after the grace period
2. **Cold Start**: When a request arrives, Knative automatically spins up a pod
3. **Active State**: Pods handle requests and scale based on concurrency
4. **Scale Down**: After 30 seconds of no traffic, pods scale back to 0

## Accessing the Service

The service is accessible via the Knative-managed route. The exact URL depends on your cluster's domain configuration:
- **OpenShift**: `https://mcpgateway-mcp-gateway.apps.<cluster-domain>`
- **Vanilla Kubernetes**: Depends on your ingress configuration and domain setup

When you make a request:
1. If scaled to zero, there will be a brief cold-start delay (typically 5-15 seconds)
2. The pod will start and handle the request
3. Subsequent requests will be fast while the pod is running
4. After 30 seconds of inactivity, the pod will terminate

## Monitoring Scale-to-Zero

### Check current pod count:
```bash
kubectl get pods -n mcp-gateway -l serving.knative.dev/service=mcpgateway
```

### Watch pods scale up/down:
```bash
kubectl get pods -n mcp-gateway -l serving.knative.dev/service=mcpgateway -w
```

### Check revision status:
```bash
kubectl get revision -n mcp-gateway
```

### View Knative Service details:
```bash
kubectl describe ksvc mcpgateway -n mcp-gateway
```

**Note:** OpenShift users can use `oc` instead of `kubectl` for all commands.

## Configuration Parameters

Key autoscaling annotations in the Knative Service:

| Annotation | Value | Description |
|------------|-------|-------------|
| `autoscaling.knative.dev/min-scale` | `0` | Minimum pods (enables scale-to-zero) |
| `autoscaling.knative.dev/max-scale` | `10` | Maximum pods under load |
| `autoscaling.knative.dev/target` | `100` | Target concurrent requests per pod |
| `autoscaling.knative.dev/scale-to-zero-pod-retention-period` | `30s` | Time to keep pods after last request |
| `autoscaling.knative.dev/metric` | `concurrency` | Metric used for scaling decisions |

## Troubleshooting

### Service not scaling to zero
```bash
# Check if there's active traffic
kubectl get podautoscaler -n mcp-gateway

# Check Knative autoscaler logs
kubectl logs -n knative-serving -l app=autoscaler
```

### Cold start taking too long
```bash
# Check pod startup time
kubectl get pods -n mcp-gateway -l serving.knative.dev/service=mcpgateway -w

# Review readiness probe configuration
kubectl describe ksvc mcpgateway -n mcp-gateway
```

### Service not ready
```bash
# Check Knative Service status
kubectl get ksvc mcpgateway -n mcp-gateway -o yaml

# Check revision status
kubectl describe revision -n mcp-gateway
```

## Reverting to Standard Deployment

If you need to revert to a standard Kubernetes Deployment:

1. Delete the Knative Service:
   ```bash
   kubectl delete ksvc mcpgateway -n mcp-gateway
   ```

2. Recreate the original Deployment and Service from your backup or version control

## Platform-Specific Notes

### Vanilla Kubernetes
- **Must install Knative Serving and an ingress controller** (Kourier recommended): [Installation Guide](https://knative.dev/docs/install/)
- Configure DNS or use Magic DNS (xip.io/nip.io/sslip.io) for local development
- Uncomment and set `ingress-class` in [`knative-serving.yaml`](knative-serving.yaml:48) to match your ingress controller
- Supported ingress controllers:
  - **Kourier** (recommended): Lightweight, Knative-specific
  - **Istio**: Full service mesh with advanced features
  - **Contour**: Envoy-based, good balance of features and performance

### OpenShift
- **Install OpenShift Serverless Operator** from OperatorHub (includes Knative + Kourier)
- Ingress is automatically configured - no need to modify [`knative-serving.yaml`](knative-serving.yaml:48)
- OpenShift Routes are automatically created and managed
- Can use `oc` instead of `kubectl` for all commands
- No separate ingress controller installation needed

## Security Best Practices

1. **Use Secrets for sensitive data:**
   ```bash
   kubectl create secret generic postgres-credentials \
     --from-literal=POSTGRES_PASSWORD=secure-password \
     -n mcp-gateway
   ```

2. **Update the Knative Service to use Secrets:**
   ```yaml
   - name: POSTGRES_PASSWORD
     valueFrom:
       secretKeyRef:
         name: postgres-credentials
         key: POSTGRES_PASSWORD
   ```

3. **Use network policies to restrict database access**
4. **Enable TLS for the Knative Service route**
5. **Regularly rotate credentials**

## Additional Resources

- [Knative Serving Documentation](https://knative.dev/docs/serving/)
- [Knative Autoscaling](https://knative.dev/docs/serving/autoscaling/)
- [Knative Installation Guide](https://knative.dev/docs/install/)
- [OpenShift Serverless Documentation](https://docs.openshift.com/serverless/)
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
