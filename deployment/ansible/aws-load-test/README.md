# MCP ContextForge AWS Load Test Infrastructure

This directory contains Ansible playbooks and automation for deploying MCP ContextForge (MCF) to AWS for load testing.

## Prerequisites

- Python 3.x with `uv` package manager
- AWS CLI configured with appropriate credentials
- An AWS account with permissions for EC2, VPC, ECS, RDS, Route 53, ACM, IAM, Secrets Manager, CloudWatch Logs, and KMS

## Pre-flight Checklist

Complete these tasks before running `make up`:

### 1. AWS Resources (create in AWS Console or CLI)

- [ ] **EC2 Key Pair**: Create a key pair in your target region
  ```bash
  aws ec2 create-key-pair --key-name mcf-keypair --region eu-west-1 \
    --query 'KeyMaterial' --output text > ~/.ssh/mcf-keypair.pem
  chmod 600 ~/.ssh/mcf-keypair.pem
  ```

- [ ] **Route 53 Hosted Zone**: Ensure your domain is managed in Route 53
  ```bash
  # List hosted zones to verify
  aws route53 list-hosted-zones --query 'HostedZones[*].[Name,Id]' --output table
  ```

- [ ] **ACM Certificate**: Request a certificate for your domain (must be in the deployment region)
  ```bash
  aws acm request-certificate \
    --domain-name "*.mcf.example.com" \
    --validation-method DNS \
    --region eu-west-1
  # Complete DNS validation in Route 53, then note the certificate ARN
  aws acm list-certificates --region eu-west-1
  ```

### 2. Local Environment

- [ ] **Set AWS credentials**:
  ```bash
  export AWS_ACCESS_KEY_ID=your-access-key
  export AWS_SECRET_ACCESS_KEY=your-secret-key
  ```

- [ ] **Verify AWS access**:
  ```bash
  aws sts get-caller-identity
  ```

### 3. Inventory Configuration

- [ ] **Copy example inventory**:
  ```bash
  cp -r inventories/example inventories/eu-west-1-dev
  ```

- [ ] **Edit `inventories/<region>/group_vars/all.yaml`**:
  | Variable | Description | Example |
  |----------|-------------|---------|
  | `prefix_v` | Unique resource prefix | `mcf-eu-west-1-dev` |
  | `region_v` | AWS region | `eu-west-1` |
  | `keypair_v` | EC2 key pair name | `mcf-keypair` |
  | `owner_v` | Resource owner (for tagging) | `Your Name` |

- [ ] **Edit `inventories/<region>/group_vars/_bastion.yaml`**:
  | Variable | Description | Example |
  |----------|-------------|---------|
  | `ansible_ssh_private_key_file` | Path to SSH private key | `~/.ssh/mcf-keypair.pem` |
  | `mcf_domain` | Base domain for the application | `mcf.example.com` |
  | `ca_certificate_arn` | ACM certificate ARN | `arn:aws:acm:eu-west-1:...` |

### 4. Verify Configuration

- [ ] **Syntax check**:
  ```bash
  make venv
  ansible-playbook --syntax-check -i inventories/eu-west-1-dev up.yaml
  ```

## Quick Start

After completing the [Pre-flight Checklist](#pre-flight-checklist):

```bash
# Bring up the complete infrastructure stack
make up AWS_REGION=eu-west-1-dev

# Wait for deployment (typically 15-20 minutes)
# Access your application at https://mcf-eu-west-1-dev.mcf.example.com
```

## Make Targets

Run `make help` to see all available targets:

| Target | Description |
|--------|-------------|
| `make help` | Show available targets and usage information |
| `make up` | Bring up the complete infrastructure stack |
| `make down` | Tear down all infrastructure (destructive!) |
| `make playbook PLAYBOOK=<name>` | Run a specific playbook from `playbooks/` |
| `make venv` | Initialize or update the Python virtual environment |
| `make ssh` | SSH to the bastion server |
| `make exec TARGET=<container>` | Execute a shell in an ECS container |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `eu-west-1` | The inventory directory to use (e.g., `eu-west-1-dev`) |
| `AWS_SSH_KEY` | (required for ssh) | Path to the SSH private key for bastion access |
| `ANSIBLE_EXTRA_VARS` | `''` | Additional variables to pass to ansible-playbook |
| `ANSIBLE_VERBOSITY` | `0` | Debug verbosity level (0-5) |

### Examples

```bash
# Bring up infrastructure in a different region
make up AWS_REGION=us-east-1-prod

# Run only the ECS playbook
make playbook PLAYBOOK=ecs-up AWS_REGION=eu-west-1-dev

# SSH to the bastion
AWS_SSH_KEY=~/.ssh/my-keypair.pem make ssh

# Execute shell in the gateway container
make exec TARGET=gateway

# Tear down with verbose output
make down AWS_REGION=eu-west-1-dev ANSIBLE_VERBOSITY=2
```

## Architecture Overview

The playbooks deploy the following AWS infrastructure:

```
+----------+     +---------------------------------------------------------------+
| Internet |     |                              VPC                              |
+----+-----+     |  +-------------------------+  +-------------------------+     |
     |           |  |    Public Subnet (AZ-a) |  |    Public Subnet (AZ-b) |     |
     v           |  |  +---------+ +--------+ |  |                         |     |
+---------+      |  |  | Bastion | |  ALB   |<---+--- HTTPS :443           |     |
|  ALB    |------+->|  | +Locust | +----+---+ |  |                         |     |
+---------+      |  |  +---------+      |     |  +-------------------------+     |
     |           |  +-------------------|-----+                                  |
     |           |                      | Path-Based Routing:                    |
     |           |                      |   /locust* -> Bastion:8089             |
     |           |                      |   /admin*  -> Gateway:4444             |
     |           |                      |   /pg*     -> pgAdmin:80               |
     |           |                      |   /redis*  -> Redis Commander:8081     |
     |           |                      |   default  -> nginx:80                 |
     |           |                      v                                        |
     |           |  +-----------------------------------------------------+      |
     |           |  |              Private Subnets (AZ-a, AZ-b)           |      |
     |           |  |  +-----------------------------------------------+  |      |
     |           |  |  |           ECS Cluster (Fargate)               |  |      |
     |           |  |  |                                               |  |      |
     +---------------->|  +-------+ +-------+ +-------+ +-------+      |  |      |
                 |  |  |  |gateway| |gateway| |gateway| | nginx |      |  |      |
                 |  |  |  +-------+ +-------+ +-------+ +-------+      |  |      |
                 |  |  |  +---------+ +-------------+ +-----------+    |  |      |
                 |  |  |  | pgadmin | |redis-cmdrer | | benchmark |    |  |      |
                 |  |  |  +---------+ +-------------+ +-----------+    |  |      |
                 |  |  +-----------------------------------------------+  |      |
                 |  +-----------------------------------------------------+      |
                 |                          |                                    |
                 |                          v                                    |
                 |  +-----------------------------------------------------+      |
                 |  |         Aurora PostgreSQL  +  ElastiCache Redis     |      |
                 |  +-----------------------------------------------------+      |
                 +---------------------------------------------------------------+
```

### Components

- **VPC**: Isolated network with public and private subnets across multiple AZs
- **Bastion Host**: SSH jump server with Locust for load testing
- **Application Load Balancer (ALB)**: HTTPS termination with path-based routing
- **ECS Cluster (Fargate)**: Serverless container orchestration
- **Aurora PostgreSQL**: Managed database with pgAdmin web UI
- **ElastiCache Redis**: Managed Redis with Redis Commander web UI
- **Route 53**: DNS management for the application domain

### ECS Services

| Service | Replicas | CPU | RAM | Port | Description |
|---------|----------|-----|-----|------|-------------|
| `gateway` | 3 | 4 vCPU | 6 GB | 4444 | MCP Gateway API server |
| `nginx` | 1 | 1 vCPU | 1 GB | 80 | Caching reverse proxy (default ALB route) |
| `fast-time` | 1 | 512m | 1 GB | 8080 | Fast Time MCP server |
| `fast-test` | 1 | 512m | 1 GB | 8880 | Fast Test MCP server |
| `benchmark` | 1 | 1 vCPU | 2 GB | 9000 | Benchmark MCP servers |
| `pgadmin` | 1 | 512m | 1 GB | 80 | PostgreSQL admin UI |
| `redis-commander` | 1 | 256m | 512 MB | 8081 | Redis admin UI |

### ALB Path-Based Routing

The Application Load Balancer routes traffic based on URL path:

| Path | Target | Description |
|------|--------|-------------|
| `/locust*` | Bastion:8089 | Locust load testing UI |
| `/admin*` | Gateway:4444 | MCP Gateway admin interface |
| `/pg*` | pgAdmin:80 | PostgreSQL admin console |
| `/redis*` | Redis Commander:8081 | Redis key browser |
| Default | nginx:80 | Main application (caching proxy) |

## Playbooks

### Main Playbooks

| Playbook | Description |
|----------|-------------|
| `up.yaml` | Orchestrates bringing up the complete infrastructure |
| `down.yaml` | Orchestrates tearing down all infrastructure |

### Component Playbooks (in `playbooks/`)

Run individual playbooks with `make playbook PLAYBOOK=<name>`:

| Playbook | Description |
|----------|-------------|
| `vpc-up.yaml` | Creates VPC, subnets, route tables, NAT gateway |
| `vpc-down.yaml` | Tears down VPC and networking |
| `security-up.yaml` | Creates security groups for all components |
| `security-down.yaml` | Removes security groups |
| `bastion-up.yaml` | Launches bastion EC2 instance with Locust |
| `bastion-down.yaml` | Terminates bastion instance |
| `ecs-ec2-up.yaml` | Launches c6i.12xlarge for ECS cluster |
| `ecs-ec2-down.yaml` | Terminates ECS EC2 instance |
| `postgres-up.yaml` | Creates Aurora PostgreSQL cluster |
| `postgres-down.yaml` | Removes RDS cluster and related resources |
| `ecs-up.yaml` | Creates ECS cluster, services, ALB, and Route 53 records |
| `ecs-down.yaml` | Removes ECS services, ALB, and DNS records |

## Custom Modules

This project includes custom Ansible modules in `library/`:

| Module | Description |
|--------|-------------|
| `cidr_allocate` | Allocates available CIDR blocks from a master range using best-fit algorithm |
| `cloudmap_namespace` | Creates/deletes AWS Cloud Map namespaces for ECS Service Connect |
| `cloudmap_info` | Retrieves information about Cloud Map namespaces |
| `ecs_service` | Enhanced ECS service management with Service Connect support |

## Directory Structure

```
aws-load-test/
├── Makefile              # Build targets for common operations
├── README.md             # This file
├── requirements.txt      # Python dependencies
├── up.yaml               # Main playbook to bring up infrastructure
├── down.yaml             # Main playbook to tear down infrastructure
├── inventories/          # Inventory configurations
│   ├── README.md         # Inventory documentation
│   └── example/          # Example inventory to copy
├── playbooks/            # Component-specific playbooks
│   ├── vpc-up.yaml
│   ├── vpc-down.yaml
│   ├── security-up.yaml
│   ├── security-down.yaml
│   ├── bastion-up.yaml
│   ├── bastion-down.yaml
│   ├── ecs-ec2-up.yaml
│   ├── ecs-ec2-down.yaml
│   ├── postgres-up.yaml
│   ├── postgres-down.yaml
│   ├── ecs-up.yaml
│   └── ecs-down.yaml
├── templates/            # Jinja2 templates
│   └── locust.service.j2
└── library/              # Custom Ansible modules
    ├── cidr_allocate.py
    ├── cloudmap_namespace.py
    ├── cloudmap_info.py
    └── ecs_service.py
```

## Configuration

See [inventories/README.md](inventories/README.md) for detailed configuration documentation.

### Key Variables

| Variable | File | Description |
|----------|------|-------------|
| `prefix_v` | group_vars/all.yaml | Resource naming prefix |
| `region_v` | group_vars/all.yaml | AWS region |
| `keypair_v` | group_vars/all.yaml | EC2 key pair name |
| `ecs_instance_type_v` | group_vars/all.yaml | ECS EC2 instance type (default: c6i.12xlarge) |
| `mcf_domain` | group_vars/_bastion.yaml | Application domain |
| `gateway_replicas` | group_vars/_bastion.yaml | Number of gateway replicas |
| `ca_certificate_arn` | group_vars/_bastion.yaml | ACM certificate ARN |
| `gateway_image_tag_v` | group_vars/_bastion.yaml | Gateway container image tag |
| `nginx_image_tag_v` | group_vars/_bastion.yaml | Nginx container image tag |

### Container Images

The deployment uses the following container images:

| Service | Image | Tag Variable |
|---------|-------|--------------|
| gateway | `ghcr.io/ibm/mcp-context-forge` | `{{ gateway_image_tag_v }}` |
| nginx | `ghcr.io/ibm/mcp-context-forge-nginx` | `{{ nginx_image_tag_v }}` |
| pgbouncer | `edoburu/pgbouncer` | `latest` |
| redis | `redis` | `latest` |

Pin specific versions in `_bastion.yaml` for reproducible deployments:
```yaml
gateway_image_tag_v: "0.7.0"
nginx_image_tag_v: "1.25.4"
```

### ECS AMI Selection

The ECS EC2 instance uses the latest Amazon Linux 2023 ECS-optimized AMI, discovered automatically via:

```yaml
amazon.aws.ec2_ami_info:
  owners: [amazon]
  filters:
    name: "al2023-ami-ecs-hvm-*-x86_64"
    state: available
```

Alternatively, you can use the SSM parameter path for reproducible AMI selection:
```bash
aws ssm get-parameter --name /aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id
```

## Load Testing

The bastion host includes Locust for load testing:

```bash
# SSH to bastion with port forwarding
ssh -L 8089:localhost:8089 -i ~/.ssh/key.pem ubuntu@<bastion-ip>

# Access Locust UI at http://localhost:8089
```

Or use the Makefile:

```bash
# Start SSH tunnel and access Locust
AWS_SSH_KEY=~/.ssh/key.pem make ssh
# Then open http://localhost:8089 in your browser
```

## Troubleshooting

### Increase Verbosity

```bash
make up ANSIBLE_VERBOSITY=2
# or
ANSIBLE_VERBOSITY=3 make playbook PLAYBOOK=ecs-up
```

### Check Running Services

```bash
# List ECS tasks
aws ecs list-tasks --cluster mcf-eu-west-1-dev-ecs-cluster

# View service logs
aws logs tail /ecs/mcf --follow

# Check EC2 instance
aws ec2 describe-instances --filters "Name=tag:Role,Values=ecs-node"
```

### Connect to Containers

```bash
# Interactive shell in gateway container
make exec TARGET=gateway

# Interactive shell in nginx container
make exec TARGET=nginx
```

### Common Issues

1. **"Could not find running bastion server"**: Ensure the bastion is running with `make playbook PLAYBOOK=bastion-up`

2. **"Error: AWS_SSH_KEY environment variable is required"**: Set the path to your SSH key: `AWS_SSH_KEY=~/.ssh/key.pem make ssh`

3. **Timeout during ECS service creation**: Services may take several minutes to stabilize. Check CloudWatch logs for container startup issues.

4. **ECS tasks not starting**: Check that the ECS EC2 instance is running and registered with the cluster: `aws ecs list-container-instances --cluster mcf-<region>-dev-ecs-cluster`

5. **Database connection failures**: Ensure security groups allow traffic between ECS tasks and Aurora.

## Documentation Links

- [Ansible Documentation](https://docs.ansible.com/)
- [AWS EC2 Dynamic Inventory](https://docs.ansible.com/ansible/latest/collections/amazon/aws/aws_ec2_inventory.html)
- [Amazon ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [Aurora PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html)
- [MCP ContextForge](https://github.com/ibm/mcp-context-forge)
