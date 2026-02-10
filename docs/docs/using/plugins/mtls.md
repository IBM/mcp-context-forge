# External Plugin mTLS Setup Guide

This guide covers how to set up mutual TLS (mTLS) authentication between the MCP Gateway and external plugin servers.

## Port Configuration

**Standard port convention:**

- **Port 8000**: Main plugin service (HTTP or HTTPS/mTLS)
- **Port 9000**: Health check endpoint (automatically starts on port+1000 when mTLS is enabled)

When mTLS is enabled, the plugin runtime automatically starts a separate HTTP-only health check server on port 9000 (configurable via `port + 1000` formula). This allows health checks without requiring mTLS client certificates.

## Certificate Generation

The MCP Gateway includes Makefile targets to manage the complete certificate infrastructure for plugin mTLS.

### Quick Start

```bash
# Generate complete mTLS infrastructure (recommended)
make certs-mcp-all

# This automatically:
# 1. Creates a Certificate Authority (CA)
# 2. Generates gateway client certificate
# 3. Reads plugins/external/config.yaml and generates server certificates for all external plugins
```

**Certificate validity**: Default is **825 days** (~2.25 years)

**Output structure**:
```
certs/mcp/
├── ca/                           # Certificate Authority
│   ├── ca.key                   # CA private key (protect!)
│   └── ca.crt                   # CA certificate
├── gateway/                      # Gateway client certificates
│   ├── client.key               # Client private key
│   ├── client.crt               # Client certificate
│   └── ca.crt                   # Copy of CA cert
└── plugins/                      # Plugin server certificates
    └── PluginName/
        ├── server.key           # Server private key
        ├── server.crt           # Server certificate
        └── ca.crt               # Copy of CA cert
```

### Makefile Targets

#### `make certs-mcp-all`

Generate complete mTLS infrastructure. This is the **recommended** command for setting up mTLS.

**What it does**:

1. Calls `certs-mcp-ca` to create the CA (if not exists)
2. Calls `certs-mcp-gateway` to create gateway client certificate (if not exists)
3. Reads `plugins/external/config.yaml` and generates certificates for all plugins with `kind: external`

**Usage**:
```bash
# Use default config file (plugins/external/config.yaml)
make certs-mcp-all

# Use custom config file
make certs-mcp-all MCP_PLUGIN_CONFIG=path/to/custom-config.yaml

# Custom certificate validity (in days)
make certs-mcp-all MCP_CERT_DAYS=365

# Combine both options
make certs-mcp-all MCP_PLUGIN_CONFIG=config.yaml MCP_CERT_DAYS=730
```

**Config file format** (`plugins/external/config.yaml`):
```yaml
plugins:
  - name: "MyPlugin"           # Certificate will be created for this plugin
    kind: "external"           # Must be "external"
    mcp:
      proto: STREAMABLEHTTP
      url: http://127.0.0.1:8000/mcp

  - name: "AnotherPlugin"
    kind: "external"
    mcp:
      proto: STREAMABLEHTTP
      url: http://127.0.0.1:8001/mcp
```

**Fallback behavior**: If the config file doesn't exist or PyYAML is not installed, example certificates are generated for `example-plugin-a` and `example-plugin-b`.

#### `make certs-mcp-ca`

Generate the Certificate Authority (CA) for plugin mTLS. This is typically called automatically by other targets.

**What it does**:

- Creates `certs/mcp/ca/ca.key` (4096-bit RSA private key)
- Creates `certs/mcp/ca/ca.crt` (CA certificate)
- Sets file permissions: `600` for `.key`, `644` for `.crt`

**Usage**:
```bash
# Generate CA (one-time setup)
make certs-mcp-ca

# Custom validity
make certs-mcp-ca MCP_CERT_DAYS=1825
```

**Safety**: Won't overwrite existing CA. To regenerate, delete `certs/mcp/ca/` first.

**⚠️  Warning**: The CA private key (`ca.key`) is critical. Protect it carefully!

#### `make certs-mcp-gateway`

Generate the gateway client certificate used by the MCP Gateway to authenticate to plugin servers.

**What it does**:

- Depends on `certs-mcp-ca` (creates CA if needed)
- Creates `certs/mcp/gateway/client.key` (4096-bit RSA private key)
- Creates `certs/mcp/gateway/client.crt` (client certificate signed by CA)
- Copies `ca.crt` to `certs/mcp/gateway/`

**Usage**:
```bash
# Generate gateway client certificate
make certs-mcp-gateway

# Custom validity
make certs-mcp-gateway MCP_CERT_DAYS=365
```

**Safety**: Won't overwrite existing certificate.

#### `make certs-mcp-plugin`

Generate a server certificate for a specific plugin.

**What it does**:

- Depends on `certs-mcp-ca` (creates CA if needed)
- Creates `certs/mcp/plugins/<PLUGIN_NAME>/server.key`
- Creates `certs/mcp/plugins/<PLUGIN_NAME>/server.crt` with Subject Alternative Names (SANs):

  - `DNS:<PLUGIN_NAME>`
  - `DNS:mcp-plugin-<PLUGIN_NAME>`
  - `DNS:localhost`

- Copies `ca.crt` to plugin directory

**Usage**:
```bash
# Generate certificate for specific plugin
make certs-mcp-plugin PLUGIN_NAME=MyCustomPlugin

# Custom validity
make certs-mcp-plugin PLUGIN_NAME=MyPlugin MCP_CERT_DAYS=365
```

**Required**: `PLUGIN_NAME` parameter must be provided.

**Use case**: Add a new plugin after running `certs-mcp-all`, or generate certificates manually.

#### `make certs-mcp-check`

Check expiry dates of all MCP certificates.

**What it does**:

- Displays expiry dates for CA, gateway client, and all plugin certificates
- Shows remaining validity period

**Usage**:
```bash
make certs-mcp-check
```

**Output example**:
```
🔍  Checking MCP certificate expiry dates...

📋 CA Certificate:
   Expires: Jan 15 10:30:45 2027 GMT

📋 Gateway Client Certificate:
   Expires: Jan 15 10:31:22 2027 GMT

📋 Plugin Certificates:
   MyPlugin: Jan 15 10:32:10 2027 GMT
   AnotherPlugin: Jan 15 10:32:45 2027 GMT
```

### Certificate Properties

All certificates generated include:

- **Algorithm**: RSA with SHA-256
- **CA Key Size**: 4096 bits
- **Client/Server Key Size**: 4096 bits
- **Default Validity**: 825 days
- **Subject Alternative Names** (plugins): DNS entries for plugin name and localhost

### Important Notes

1. **All `ca.crt` files are identical** - They are copies of the root CA certificate distributed to each location for convenience
2. **Safety features** - Commands won't overwrite existing certificates. To regenerate, delete the target directory first
3. **File permissions** - Automatically set to secure values:

   - Private keys (`.key`): `600` (owner read/write only)
   - Certificates (`.crt`): `644` (world-readable)

4. **Configuration variables**:

   - `MCP_CERT_DAYS`: Certificate validity in days (default: 825)
   - `MCP_PLUGIN_CONFIG`: Path to plugin config file (default: `plugins/external/config.yaml`)

## Configuration Options

You can configure mTLS using either YAML files or environment variables.

### Option 1: YAML Configuration

#### Server Configuration (Plugin)

In your plugin config file (e.g., `plugins/test.yaml`):

```yaml
plugins:
  - name: "ReplaceBadWordsPlugin"
    kind: "plugins.regex_filter.search_replace.SearchReplacePlugin"
    # ... plugin config ...

server_settings:
  host: "127.0.0.1"
  port: 8000
  tls:
    certfile: certs/mcp/plugins/ReplaceBadWordsPlugin/server.crt
    keyfile: certs/mcp/plugins/ReplaceBadWordsPlugin/server.key
    ca_bundle: certs/mcp/plugins/ReplaceBadWordsPlugin/ca.crt
    ssl_cert_reqs: 2  # 2 = CERT_REQUIRED (enforce client certificates)
```

Start the server (for testing):
```bash
PYTHONPATH=. PLUGINS_CONFIG_PATH="plugins/test.yaml" \
  python3 mcpgateway/plugins/framework/external/mcp/server/runtime.py
```

#### Client Configuration (Gateway)

In your gateway plugin config file (e.g., `plugins/external/config-client.yaml`):

```yaml
plugins:
  - name: "ReplaceBadWordsPlugin"
    kind: "external"
    mcp:
      proto: STREAMABLEHTTP
      url: https://127.0.0.1:8000/mcp
      tls:
        certfile: certs/mcp/gateway/client.crt
        keyfile: certs/mcp/gateway/client.key
        ca_bundle: certs/mcp/gateway/ca.crt
        verify: true
        check_hostname: false
```

### Option 2: Environment Variables

#### Server Environment Variables

```bash
# Server configuration
export PLUGINS_SERVER_HOST="127.0.0.1"
export PLUGINS_SERVER_PORT="8000"
export PLUGINS_SERVER_SSL_ENABLED="true"

# TLS/mTLS configuration
export PLUGINS_SERVER_SSL_KEYFILE="certs/mcp/plugins/ReplaceBadWordsPlugin/server.key"
export PLUGINS_SERVER_SSL_CERTFILE="certs/mcp/plugins/ReplaceBadWordsPlugin/server.crt"
export PLUGINS_SERVER_SSL_CA_CERTS="certs/mcp/plugins/ReplaceBadWordsPlugin/ca.crt"
export PLUGINS_SERVER_SSL_CERT_REQS="2"  # 2 = CERT_REQUIRED
```

Start the server (YAML without `server_settings` section for testing):
```bash
PYTHONPATH=. PLUGINS_CONFIG_PATH="plugins/test.yaml" \
  python3 mcpgateway/plugins/framework/external/mcp/server/runtime.py
```

#### Client Environment Variables

```bash
export PLUGINS_CLIENT_MTLS_CERTFILE="certs/mcp/gateway/client.crt"
export PLUGINS_CLIENT_MTLS_KEYFILE="certs/mcp/gateway/client.key"
export PLUGINS_CLIENT_MTLS_CA_BUNDLE="certs/mcp/gateway/ca.crt"
export PLUGINS_CLIENT_MTLS_VERIFY="true"
export PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="false"
```

Run your gateway code (YAML without `tls` section in `mcp` config).

## Environment Variable Reference

### Server Variables (Plugin)

| Variable | Description | Example |
|----------|-------------|---------|
| `PLUGINS_SERVER_HOST` | Server bind address | `127.0.0.1` |
| `PLUGINS_SERVER_PORT` | Server bind port | `8000` |
| `PLUGINS_SERVER_UDS` | Unix domain socket path (Streamable HTTP only; no TLS) | `/var/run/mcp-plugin.sock` |
| `PLUGINS_SERVER_SSL_ENABLED` | Enable SSL/TLS | `true` |
| `PLUGINS_SERVER_SSL_KEYFILE` | Path to server private key | `certs/.../server.key` |
| `PLUGINS_SERVER_SSL_CERTFILE` | Path to server certificate | `certs/.../server.crt` |
| `PLUGINS_SERVER_SSL_CA_CERTS` | Path to CA bundle | `certs/.../ca.crt` |
| `PLUGINS_SERVER_SSL_CERT_REQS` | Client cert requirement (0-2) | `2` |
| `PLUGINS_SERVER_SSL_KEYFILE_PASSWORD` | Password for encrypted key | `password` |

!!! note
    `PLUGINS_SERVER_UDS` and TLS are mutually exclusive. UDS runs without TLS by design.

**`ssl_cert_reqs` values:**

- `0` = `CERT_NONE` - No client certificate required
- `1` = `CERT_OPTIONAL` - Client certificate requested but not required
- `2` = `CERT_REQUIRED` - Client certificate required (mTLS)

### Client Variables (Gateway)

| Variable | Description | Example |
|----------|-------------|---------|
| `PLUGINS_CLIENT_MTLS_CERTFILE` | Path to client certificate | `certs/.../client.crt` |
| `PLUGINS_CLIENT_MTLS_KEYFILE` | Path to client private key | `certs/.../client.key` |
| `PLUGINS_CLIENT_MTLS_CA_BUNDLE` | Path to CA bundle | `certs/.../ca.crt` |
| `PLUGINS_CLIENT_MTLS_VERIFY` | Verify server certificate | `true` |
| `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME` | Verify server hostname | `false` |
| `PLUGINS_CLIENT_MTLS_KEYFILE_PASSWORD` | Password for encrypted key | `password` |

## Testing mTLS

### Test without TLS

```bash
# Server
PYTHONPATH=. PLUGINS_CONFIG_PATH="plugins/test.yaml" \
  PLUGINS_SERVER_HOST="127.0.0.1" \
  PLUGINS_SERVER_PORT="8000" \
  PLUGINS_SERVER_SSL_ENABLED="false" \
  python3 mcpgateway/plugins/framework/external/mcp/server/runtime.py &

# Client config should use: url: http://127.0.0.1:8000/mcp
```

### Test with mTLS (YAML)

```bash
# Server (config has server_settings.tls section)
PYTHONPATH=. PLUGINS_CONFIG_PATH="plugins/test.mtls.yaml" \
  python3 mcpgateway/plugins/framework/external/mcp/server/runtime.py &

# Client (config has mcp.tls section)
python3 your_client.py
```

### Test with mTLS (Environment Variables)

```bash
# Server (config has no server_settings section)
# Note: When mTLS is enabled, a health check server automatically starts on port 9000 (port+1000)
PYTHONPATH=. \
  PLUGINS_CONFIG_PATH="plugins/test.yaml" \
  PLUGINS_SERVER_HOST="127.0.0.1" \
  PLUGINS_SERVER_PORT="8000" \
  PLUGINS_SERVER_SSL_ENABLED="true" \
  PLUGINS_SERVER_SSL_KEYFILE="certs/mcp/plugins/ReplaceBadWordsPlugin/server.key" \
  PLUGINS_SERVER_SSL_CERTFILE="certs/mcp/plugins/ReplaceBadWordsPlugin/server.crt" \
  PLUGINS_SERVER_SSL_CA_CERTS="certs/mcp/plugins/ReplaceBadWordsPlugin/ca.crt" \
  PLUGINS_SERVER_SSL_CERT_REQS="2" \
  python3 mcpgateway/plugins/framework/external/mcp/server/runtime.py &

# Client (config has no mcp.tls section)
PLUGINS_CLIENT_MTLS_CERTFILE="certs/mcp/gateway/client.crt" \
  PLUGINS_CLIENT_MTLS_KEYFILE="certs/mcp/gateway/client.key" \
  PLUGINS_CLIENT_MTLS_CA_BUNDLE="certs/mcp/gateway/ca.crt" \
  PLUGINS_CLIENT_MTLS_VERIFY="true" \
  PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="false" \
  python3 your_client.py
```

## How mTLS Works

1. **Certificate Authority (CA)**: A single root CA (`ca.crt`) signs both client and server certificates
2. **Server Certificate**: Plugin server presents its certificate (`server.crt`) to clients
3. **Client Certificate**: Gateway presents its certificate (`client.crt`) to the plugin server
4. **Mutual Verification**: Both parties verify each other's certificates against the CA bundle
5. **Secure Channel**: After mutual authentication, all communication is encrypted

## Configuration Priority

Environment variables take precedence over YAML configuration:

- If `PLUGINS_SERVER_SSL_ENABLED=true`, env vars override `server_settings.tls`
- If client env vars are set, they override `mcp.tls` in YAML

## Hostname Verification (`check_hostname`)

### Overview
`check_hostname` is a **client-side only** setting that verifies the server's certificate matches the hostname/IP you're connecting to.

### How It Works
The client checks if the URL hostname matches entries in the server certificate's:

- **Common Name (CN)**: `CN=mcp-plugin-ReplaceBadWordsPlugin`
- **Subject Alternative Names (SANs)**: DNS names or IP addresses

### Checking Certificate SANs
```bash
# View DNS and IP SANs in server certificate
openssl x509 -in certs/mcp/plugins/ReplaceBadWordsPlugin/server.crt -text -noout | grep -A 5 "Subject Alternative Name"

# Example output:
# X509v3 Subject Alternative Name:
#     DNS:ReplaceBadWordsPlugin, DNS:mcp-plugin-ReplaceBadWordsPlugin, DNS:localhost
```

### Configuration Examples

#### Option 1: Use `localhost` with `check_hostname: true`
```yaml
# Client config
mcp:
  url: https://localhost:8000/mcp
  tls:
    check_hostname: true  # Works because "localhost" is in DNS SANs
```

Or with environment variables:
```bash
export PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="true"
# Connect to: https://localhost:8000/mcp
```

#### Option 2: Use IP address with `check_hostname: false`
```yaml
# Client config
mcp:
  url: https://127.0.0.1:8000/mcp
  tls:
    check_hostname: false  # Required because 127.0.0.1 is not in SANs
```

Or with environment variables:
```bash
export PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="false"
# Connect to: https://127.0.0.1:8000/mcp
```

#### Option 3: Add IP SANs to certificate (Advanced)
If you need `check_hostname: true` with IP addresses, regenerate certificates with IP SANs:

```bash
# Modify Makefile to add IP SANs when generating certificates
# Add to server.ext or openssl command:
# subjectAltName = DNS:localhost, DNS:plugin-name, IP:127.0.0.1, IP:0.0.0.0
```

### Server-Side Hostname Verification
There is **no** `check_hostname` setting on the server side. The server only:

1. Verifies the client certificate is signed by the trusted CA
2. Checks if `ssl_cert_reqs=2` (CERT_REQUIRED) to enforce client certificates

### Testing Hostname Verification

#### Test 1: Valid hostname (should succeed)
```bash
# Server bound to 0.0.0.0 (accepts all interfaces)
PLUGINS_SERVER_HOST="0.0.0.0" ...

# Client connecting to localhost with hostname check
export PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="true"
# URL: https://localhost:8000/mcp
# Result: ✅ Success (localhost is in DNS SANs)
```

#### Test 2: IP address with hostname check (should fail)
```bash
# Client connecting to IP with hostname check
export PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="true"
# URL: https://127.0.0.1:8000/mcp
# Result: ❌ Fails with "IP address mismatch, certificate is not valid for '127.0.0.1'"
```

## Troubleshooting

### Connection Refused
- Ensure server is running: `lsof -i :8000`
- Check server logs for startup errors
- Verify server is bound to correct interface (0.0.0.0 for all, 127.0.0.1 for localhost only)
- Note: When mTLS is enabled, a health check server also runs on port 9000 (port+1000)

### Certificate Verification Failed
- Verify CA bundle matches on both sides: `md5 certs/**/ca.crt`
- Check certificate paths are correct
- Ensure certificates haven't expired: `openssl x509 -in cert.crt -noout -dates`

### Hostname Verification Failed
Error: `certificate verify failed: IP address mismatch` or `Hostname mismatch`

**Solutions:**

1. **Use hostname from SANs**: Connect to `https://localhost:8000` instead of `https://127.0.0.1:8000`
2. **Disable hostname check**: Set `check_hostname: false` or `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="false"`
3. **Add IP to SANs**: Regenerate certificates with IP SANs included

## mTLS Deployment Hardening Guidelines

For production deployments, follow these security best practices to ensure robust mTLS configuration:

| Category | Recommendation | Configuration / Option | Notes |
| --- | --- | --- | --- |
| **Certificate Verification** | Keep hostname and certificate chain verification enabled. | **YAML**: `check_hostname: true` and valid `ca_bundle`<br>**Environment**: `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="true"` and valid `PLUGINS_CLIENT_MTLS_CA_BUNDLE` or `PLUGINS_SERVER_SSL_CA_CERTS` | Only disable in trusted, local test setups. |
| **CA Management** | Use a dedicated CA for gateway ↔ plugin certificates. | **YAML**: `ca_bundle: certs/mcp/gateway/ca.crt`<br>**Environment**: `PLUGINS_SERVER_SSL_CA_CERTS` or `PLUGINS_CLIENT_MTLS_CA_BUNDLE` | Ensures trust is limited to your deployment's CA. |
| **Certificate Rotation** | Regenerate and redeploy certificates periodically. | **Local/Docker**: Use Makefile targets: `make certs-mcp-all`, `make certs-mcp-check`<br>**Kubernetes**: Use [cert-manager](https://cert-manager.io/) for automated certificate lifecycle management | Recommended: short-lived certs (e.g. 90–180 days). Configure with `MCP_CERT_DAYS` variable for Makefile targets. |
| **Key Protection** | Limit read access to private key files. | **YAML**: `keyfile` paths (e.g., `server.key`, `client.key`)<br>**Environment**: `PLUGINS_SERVER_SSL_KEYFILE` or `PLUGINS_CLIENT_MTLS_KEYFILE`<br>**File permissions**: `600` (owner read/write only) | Keys should be owned and readable only by the service account. |
| **TLS Version Enforcement** | Enforce TLS 1.2 or newer. | Controlled by Python's `ssl` defaults or runtime settings. | No additional configuration required; defaults are secure. |
| **Health Endpoint Exposure** | Bind health endpoints to localhost only. | **YAML**: `server_settings.host: 127.0.0.1`<br>**Environment**: `PLUGINS_SERVER_HOST="127.0.0.1"` | Prevents unauthenticated HTTP access from external hosts. Health check server (port+1000) is HTTP-only. |
| **Logging & Diagnostics** | Enable debug logs for TLS handshake troubleshooting. | `LOG_LEVEL=DEBUG` or `--verbose` | Logs cert subjects and handshake results (safe to enable temporarily). |
| **Insecure Mode Control** | Disable insecure (non-TLS) connections in production. | **Environment**: `PLUGINS_SERVER_SSL_ENABLED="true"`<br>Set `ssl_cert_reqs: 2` (CERT_REQUIRED) for mTLS enforcement | Guarantees all plugin communications use mTLS. |
| **Configuration Validation** | Fail fast on missing or invalid TLS configuration. | Enabled automatically at startup. | Ensures system won't silently downgrade to HTTP. |

### Implementation Checklist

When deploying plugin mTLS in production:

1. **Generate Certificates**:

   - **Local/Docker**: Use `make certs-mcp-all` to create complete certificate infrastructure
   - **Kubernetes**: Deploy [cert-manager](https://cert-manager.io/) and configure Certificate resources for automated issuance and renewal

2. **Verify Expiration**:

   - **Local/Docker**: Run `make certs-mcp-check` regularly to monitor certificate validity
   - **Kubernetes**: cert-manager automatically monitors and renews certificates before expiration

3. **Secure Private Keys**: Ensure all `.key` files have `600` permissions and are owned by service accounts (or stored in Kubernetes Secrets with appropriate RBAC)
4. **Enable Hostname Verification**: Set `check_hostname: true` or `PLUGINS_CLIENT_MTLS_CHECK_HOSTNAME="true"` unless using IP addresses
5. **Configure Health Checks**: Bind health servers to `127.0.0.1` to prevent external access
6. **Enforce mTLS**: Set `PLUGINS_SERVER_SSL_CERT_REQS="2"` to require client certificates
7. **Monitor Logs**: Enable `LOG_LEVEL=DEBUG` temporarily during initial deployment to verify handshakes
8. **Plan Rotation**:

   - **Local/Docker**: Schedule certificate rotation every 90-180 days using `MCP_CERT_DAYS` parameter
   - **Kubernetes**: Configure cert-manager Certificate resources with appropriate `renewBefore` duration (typically 30 days before expiration)

### Security Validation

After deployment, verify your mTLS configuration:

```bash
# 1. Check certificate expiration dates
make certs-mcp-check

# 2. Verify file permissions on private keys
find certs/mcp -name "*.key" -exec ls -la {} \;

# 3. Test certificate verification
openssl verify -CAfile certs/mcp/ca/ca.crt certs/mcp/gateway/client.crt

# 4. Confirm TLS version enforcement
openssl s_client -connect localhost:8000 -tls1_1 < /dev/null
# Should fail with "no protocols available" or similar

# 5. Test hostname verification (should succeed)
curl --cert certs/mcp/gateway/client.pem \
     --cacert certs/mcp/gateway/ca.crt \
     https://localhost:8000/health

# 6. Test without client cert (should fail if ssl_cert_reqs=2)
curl --cacert certs/mcp/gateway/ca.crt \
     https://localhost:8000/health
```
