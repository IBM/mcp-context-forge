# Playbook Reorganization Summary

## Overview
The VPC-related playbooks have been reorganized into three separate concerns for better modularity and dependency management.

## New Structure

### Creation Order (up.yaml)
1. **vpc-up.yaml** - VPC and networking infrastructure
   - VPC creation
   - Public/private subnets
   - Internet Gateway
   - NAT Gateway
   - Route tables

2. **security-up.yaml** - All security groups
   - bastion-sg
   - ecs-feed-sg
   - ecs-web-sg
   - aurora-postgresql-sg
   - efs-sg
   - alb-sg
   - Updates ecs-web-sg with ALB access rule (after ALB SG exists)

3. **bastion-up.yaml** - Bastion host creation
   - EC2 instance creation
   - SSH availability wait

4. **efs-up.yaml** - EFS resources (no security group creation)

5. **postgis-up.yaml** - PostgreSQL resources (no security group creation)

6. **ecs-up.yaml** - ECS resources (no security group creation/updates)

### Deletion Order (down.yaml)
1. **ecs-down.yaml** - ECS resources
2. **postgis-down.yaml** - PostgreSQL resources (no security group deletion)
3. **efs-down.yaml** - EFS resources (no security group deletion)
4. **bastion-down.yaml** - Bastion host
5. **security-down.yaml** - All security groups (in reverse dependency order)
6. **vpc-down.yaml** - VPC and networking infrastructure

## Key Changes

### Security Group Management
All security groups are now centrally managed in:
- **security-up.yaml** - Creates all security groups with proper dependency ordering
- **security-down.yaml** - Deletes all security groups in reverse order

Security groups removed from:
- `efs-up.yaml` / `efs-down.yaml` (efs-sg)
- `postgis-up.yaml` / `postgis-down.yaml` (aurora-postgresql-sg)
- `ecs-up.yaml` (alb-sg and all security group updates)

### Bastion Host Management
Bastion host creation separated into:
- **bastion-up.yaml** - Creates the bastion instance
- **bastion-down.yaml** - Terminates the bastion instance

Removed from:
- `vpc-up.yaml` / `vpc-down.yaml`

### Security Group Dependency Order

**Creation order (security-up.yaml):**
1. bastion-sg (no dependencies)
2. ecs-feed-sg (no dependencies)
3. alb-sg (no dependencies)
4. ecs-web-sg (depends on: alb-sg)
5. aurora-postgresql-sg (depends on: bastion-sg, ecs-feed-sg, ecs-web-sg)
6. efs-sg (depends on: bastion-sg, ecs-feed-sg)

Note: ALB SG is created before ECS Web SG so that ECS Web SG can reference it directly without requiring an update step.

**Deletion order (security-down.yaml):**
1. alb-sg
2. efs-sg
3. aurora-postgresql-sg
4. ecs-web-sg
5. ecs-feed-sg
6. bastion-sg

## Backup Files
Original files backed up as:
- `playbooks/vpc-up.yaml.bak`
- `playbooks/vpc-down.yaml.bak`

## Benefits
1. **Clearer separation of concerns** - VPC, security, and bastion are distinct
2. **Better dependency management** - Security groups created in proper order
3. **Easier troubleshooting** - Issues isolated to specific playbook
4. **Reusability** - Can run security updates independently
5. **Centralized security** - All security groups in one place
