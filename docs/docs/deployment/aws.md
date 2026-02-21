# 🟧 AWS

ContextForge can be deployed to AWS using multiple container-based services:

- **ECS (Fargate or EC2-backed)**
- **EKS (Elastic Kubernetes Service)**
- **EC2 (direct VM hosting with Docker)**

---

## 🚀 Option 1: ECS (Fargate)

ECS is a fully managed container orchestration service. Use it to deploy ContextForge without managing servers.

### Steps

1. **Build and push your image:**

```bash
docker build -t YOUR_ECR_URI/mcpgateway .
aws ecr get-login-password | docker login --username AWS --password-stdin YOUR_ECR_URI
docker push YOUR_ECR_URI/mcpgateway
```

2. **Create an ECS Task Definition:**

   - Use port `4444`
   - Mount a secret or config for your `.env` (or set environment variables manually)

3. **Create a Service:**

   - Use a Load Balancer (Application LB)
   - Map `/` or `/admin` to port `4444`

---

## 🚀 Option 2: EKS

Use the same [Kubernetes deployment guide](kubernetes.md) and run on Amazon EKS.

You can:

* Use `kubectl` + `eksctl`
* Store `.env` as a Secret or ConfigMap
* Use AWS Load Balancer Controller or NGINX Ingress

---

## 🚀 Option 3: EC2 (Docker)

1. Launch a VM (e.g., Ubuntu)
2. Install Docker
3. Copy your `.env` file and build the container:

```bash
scp .env ec2-user@host:/home/ec2-user
ssh ec2-user@host
docker build -t mcpgateway .
docker run -p 80:4444 --env-file .env mcpgateway
```

---

## 🛡️ Security Tips

* Set `AUTH_REQUIRED=true` in production
* Use `JWT_SECRET_KEY` and `AUTH_ENCRYPTION_SECRET`
* Terminate TLS at the ELB level, or use Caddy/Nginx in-container if needed

---

## 📡 DNS & Access

You can point Route53 or your DNS provider to the Load Balancer hostname.

Example:

```bash
gateway.example.com -> my-elb-1234.us-west-2.elb.amazonaws.com
```

---
