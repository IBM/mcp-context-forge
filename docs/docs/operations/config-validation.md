# Configuration Validation

MCP Gateway provides robust configuration validation tools to help operators catch misconfigurations early and ensure reliable deployments.

## JSON Schema Export

Generate a machine-readable schema for all configuration options:

```bash
# Export schema to stdout
python -m mcpgateway.config --schema

# Save schema to file
python -m mcpgateway.config --schema > config.schema.json
```

Use this schema with validation tools in your deployment pipeline:

```bash
# Validate with ajv-cli
npx ajv-cli validate -s config.schema.json -d .env.json

# Validate with jsonschema (Python)
python -c "
import json, jsonschema
from mcpgateway.config import generate_settings_schema
schema = generate_settings_schema()
with open('.env.json') as f:
    jsonschema.validate(json.load(f), schema)
"
```

## Environment File Validation

Validate your `.env` file before deployment:

```bash
# Validate default .env file
python -m mcpgateway.scripts.validate_env

# Validate specific file
python -m mcpgateway.scripts.validate_env .env.example

# Use in Makefile
make check-env
```

The validator checks for:

- **Type validation**: Ensures values match expected types (integers, URLs, enums)
- **Security warnings**: Detects weak passwords, default secrets, insecure configurations
- **Range validation**: Verifies ports, timeouts, and limits are within valid ranges
- **Format validation**: Validates URLs, email addresses, and structured data

## Example Validation Output

### Valid Configuration
```bash
$ python -m mcpgateway.scripts.validate_env .env.example
✅ .env validated successfully with no warnings.
```

### Invalid Configuration
```bash
$ python -m mcpgateway.scripts.validate_env .env.invalid
❌ Invalid configuration: ValidationError
2 validation errors for Settings
port
  Input should be greater than 0 [type=greater_than, input=-1]
log_level
  Input should be 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRITICAL' [type=literal_error, input='INVALID']
```

### Security Warnings
```bash
$ python -m mcpgateway.scripts.validate_env .env.dev
⚠️ Default admin password detected! Please change PLATFORM_ADMIN_PASSWORD immediately.
⚠️ JWT_SECRET_KEY: Default/weak secret detected! Please set a strong, unique value for production.
❌ Configuration has security warnings. Please address them for production use.
```

## CI/CD Integration

Add validation to your deployment pipeline:

### GitHub Actions
```yaml
- name: Validate Configuration
  run: |
    python -m mcpgateway.scripts.validate_env .env.production
    if [ $? -ne 0 ]; then
      echo "Configuration validation failed"
      exit 1
    fi
```

### Docker Build
```dockerfile
COPY .env.example /app/.env
RUN python -m mcpgateway.scripts.validate_env /app/.env
```

## Configuration Types

The following field types are strictly validated:

### URLs and Endpoints
- `APP_DOMAIN`: Must be valid HTTP/HTTPS URL
- `SSO_*_ISSUER`: Valid OIDC issuer URLs

### Enumerations
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR, CRITICAL
- `CACHE_TYPE`: memory, redis, database
- `TRANSPORT_TYPE`: http, ws, sse, all

### Numeric Ranges
- `PORT`: 1-65535
- `DB_POOL_SIZE`: Positive integer
- `TOKEN_EXPIRY`: Positive integer (minutes)

### Security Fields
- `JWT_SECRET_KEY`: SecretStr, minimum 32 characters
- `AUTH_ENCRYPTION_SECRET`: SecretStr, minimum 32 characters
- Password fields: Minimum 12 characters with complexity requirements

## Best Practices

1. **Validate Early**: Run validation in development and CI before deployment
2. **Use Strong Secrets**: Generate cryptographically secure secrets for production
3. **Environment-Specific Configs**: Maintain separate `.env` files per environment
4. **Schema Versioning**: Pin schema versions in deployment scripts
5. **Security Scanning**: Regularly audit configurations for security issues

## Troubleshooting

### Common Validation Errors

**Invalid Port Range**
```
port: Input should be greater than 0 and less than 65536
```
Fix: Use valid port number (1-65535)

**Invalid URL Format**
```
app_domain: Input should be a valid URL
```
Fix: Ensure URLs include protocol (`http://` or `https://`)

**Weak Secrets**
```
JWT_SECRET_KEY: Secret should be at least 32 characters long
Admin password should be at least 8 characters long
```
Fix: Generate longer, more complex secrets

### Getting Help

- Use `python -m mcpgateway.config --help` for CLI options
