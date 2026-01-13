# Security Groups Architecture

```mermaid
graph TB
    subgraph "External Traffic"
        MY_IP["My IP Address"]
        INTERNET["Internet (0.0.0.0/0)"]
    end

    subgraph "Security Groups"
        BASTION_SG["bastion-sg<br/>Port 22"]
        ALB_SG["alb-sg<br/>Port 80"]
        ECS_FEED_SG["ecs-feed-sg<br/>Port 443 outbound"]
        ECS_WEB_SG["ecs-web-sg<br/>Port 80, 443"]
        AURORA_SG["aurora-postgresql-sg<br/>Port 5432"]
        EFS_SG["efs-sg<br/>Port 2049"]
    end

    subgraph "Resources"
        BASTION["Bastion Host"]
        ALB["Application Load Balancer"]
        ECS_FEED["ECS Feed Tasks"]
        ECS_WEB["ECS Web Tasks"]
        AURORA["Aurora PostgreSQL"]
        EFS["EFS File System"]
    end

    %% External to Security Groups
    MY_IP -->|SSH:22| BASTION_SG
    MY_IP -->|HTTP:80| ALB_SG
    INTERNET -->|HTTPS:443| ECS_FEED_SG
    INTERNET -->|HTTPS:443| ECS_WEB_SG

    %% Security Groups to Resources
    BASTION_SG --> BASTION
    ALB_SG --> ALB
    ECS_FEED_SG --> ECS_FEED
    ECS_WEB_SG --> ECS_WEB
    AURORA_SG --> AURORA
    EFS_SG --> EFS

    %% Inter-Security Group Rules
    ALB_SG -.->|HTTP:80| ECS_WEB_SG
    BASTION_SG -.->|PostgreSQL:5432| AURORA_SG
    ECS_FEED_SG -.->|PostgreSQL:5432| AURORA_SG
    ECS_WEB_SG -.->|PostgreSQL:5432| AURORA_SG
    BASTION_SG -.->|NFS:2049| EFS_SG
    ECS_FEED_SG -.->|NFS:2049| EFS_SG

    %% Traffic Flow
    ALB -->|forward| ECS_WEB
    ECS_FEED -->|queries| AURORA
    ECS_WEB -->|queries| AURORA
    ECS_FEED -->|mounts| EFS
    BASTION -->|manages| AURORA
    BASTION -->|mounts| EFS

    classDef sgStyle fill:#e1f5ff,stroke:#0066cc,stroke-width:2px
    classDef resourceStyle fill:#fff4e6,stroke:#ff9900,stroke-width:2px
    classDef externalStyle fill:#f0f0f0,stroke:#666,stroke-width:2px

    class BASTION_SG,ALB_SG,ECS_FEED_SG,ECS_WEB_SG,AURORA_SG,EFS_SG sgStyle
    class BASTION,ALB,ECS_FEED,ECS_WEB,AURORA,EFS resourceStyle
    class MY_IP,INTERNET externalStyle
```

## Legend

- **Solid arrows (→)**: External traffic sources and security group attachments
- **Dotted arrows (-.→)**: Inter-security-group access rules
- **Blue boxes**: Security Groups
- **Orange boxes**: AWS Resources
- **Gray boxes**: External traffic sources
