# CyberFraud Context Forge Setup

This guide explains how to set up Context Forge for the CyberFraud project.

## Prerequisites

1. Clone the repository:
   ```bash
   git clone https://github.ibm.com/cyberfraud/cyberfraud-mcp-context-forge.git
   cd cyberfraud-mcp-context-forge
   ```

2. Copy the additional roles configuration file from the management service repository:
   - Source: [additional_roles_in_db.json](https://github.ibm.com/cyberfraud/cyberfraud-mcp-management-service/blob/develop/additional_roles_in_db.json)
   - Destination: Root of the cloned repository

## Environment Configuration

### Required: Bootstrap Roles

Add the following environment variables to your `.env` file to enable role bootstrapping:

```bash
MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_ENABLED=true
MCPGATEWAY_BOOTSTRAP_ROLES_IN_DB_FILE=additional_roles_in_db.json
```

### Required: Disable Auto-Create Personal Teams

Disable automatic creation of personal teams:

```bash
AUTO_CREATE_PERSONAL_TEAMS=false
```

### Optional: JWT RS256 Algorithm

If you need to use RS256 algorithm for JWT tokens instead of the default HS256:

1. Generate RSA key pair:
   ```bash
   openssl genpkey -algorithm RSA -out jwt.private.pem -pkeyopt rsa_keygen_bits:2048
   openssl rsa -in jwt.private.pem -pubout -out jwt.public.pem
   ```

2. Add the following environment variables to your `.env` file:
   ```bash
   JWT_ALGORITHM=RS256
   JWT_PUBLIC_KEY_PATH=jwt.public.pem
   JWT_PRIVATE_KEY_PATH=jwt.private.pem
   ```

## Starting the Service

Once you have completed the above configuration changes, start the service:

```bash
make dev
```

For production deployment:

```bash
make serve
```

## Verification

After starting the service, verify that:
- The roles from `additional_roles_in_db.json` are loaded into the database
- Personal teams are not automatically created for new users
- JWT authentication is working with your configured algorithm

## VS Code Debug Configuration

For debugging in VS Code, add the following configuration to your `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug MCP Gateway",
            "type": "python",
            "request": "launch",
            "module": "mcpgateway.cli",
            "args": ["--host", "0.0.0.0", "--port", "8000"],
            "env": {
                "DEBUG": "true",
                "LOG_LEVEL": "DEBUG",
                "ENVIRONMENT": "development"
            },
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "python": "${workspaceFolder}/.venv/bin/python"
        }
    ]
}
```