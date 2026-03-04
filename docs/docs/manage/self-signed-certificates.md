
# Using Self-Signed Certificates with MCP Servers

When integrating with internal or development MCP servers that use self-signed TLS certificates, you must provide the Certificate Authority (CA) root certificate to the gateway. This allows the gateway to verify the identity of the remote server and establish a secure connection.

This guide explains how to upload and manage custom CA certificate bundles for registered MCP servers.

## Overview

ContextForge supports connecting to servers with self-signed certificates by allowing administrators to upload custom CA certificate bundles. These certificates are stored securely in the database and used automatically when establishing HTTPS connections to the associated MCP server.

## Prerequisites

-   You must have administrator access to ContextForge.
-   You need the root CA certificate file (or the full certificate chain) in PEM format. Supported file extensions are `.pem`, `.crt`, `.cer`, and `.cert`.
-   Maximum file size: **10 MB per certificate file**.
-   The certificates must be valid PEM-encoded X.509 certificates.

## Steps to Add a CA Certificate

### 1. Navigate to the Admin Panel

Log in to ContextForge and go to the **Admin** section.

### 2. Go to Gateways Tab

In the admin panel, select the **Gateways** tab. This displays a list of registered MCP servers.

### 3. Register or Edit a Server

-   **For a new server**: Click "Add Gateway" and fill in the server details (name, URL, transport type, authentication).
-   **For an existing server**: Find the server in the list and click the edit button.

### 4. Upload the CA Certificate

In the gateway configuration form, you'll find a **CA Certificate** upload section:

-   **Drag and Drop**: Drag your certificate file(s) directly into the upload zone.
-   **Click to Browse**: Click the upload area to open a file browser and select certificate files.
-   **Multiple Files**: You can select multiple certificate files if your certificate chain is split across files (e.g., root CA and intermediate CAs).

**Accepted file types**: `.pem`, `.crt`, `.cer`, `.cert`

### 5. Certificate Validation

The system performs comprehensive validation when you upload certificates:

#### Automatic Validation Checks

1. **File Size**: Each file must be under 10 MB
2. **File Extension**: Only `.pem`, `.crt`, `.cer`, and `.cert` files are accepted
3. **PEM Format**: Validates proper PEM structure with `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----` markers
4. **Base64 Content**: Ensures the certificate content between markers is valid base64-encoded data
5. **Certificate Length**: Verifies certificates meet minimum length requirements (typically >100 characters)

#### Multiple File Handling

When you upload multiple certificate files:

-   The system automatically detects **root CA certificates** (self-signed certificates where Subject equals Issuer)
-   Certificates are **automatically ordered** with root CAs first, followed by intermediate certificates
-   All files are **concatenated** into a single certificate bundle in the correct order
-   Each file is validated individually before concatenation

#### Validation Feedback

After upload, you'll see:

-   ✅ **Success**: Green checkmark with "All certificates validated successfully!" if all files are valid
-   ❌ **Error**: Red X with specific error messages for any invalid files
-   **Per-file status**: Each uploaded file shows its validation status and file size
-   **Certificate type**: Root CAs are labeled as "(Root CA)"

### 6. Save the Gateway Configuration

After successful validation:

-   Click the **Save** or **Update** button
-   The certificate bundle is stored in the database as a PEM-encoded string
-   If Ed25519 signing is enabled, the certificate is digitally signed for tamper protection

## How It Works

### Storage

-   CA certificates are stored in the `gateways` table in the database
-   Field: `ca_certificate` (stored as TEXT/BLOB)
-   Optional signature field: `ca_certificate_sig` (for tamper detection when Ed25519 signing is enabled)

### Usage During Tool Invocation

When the gateway invokes a tool from an MCP server with a custom CA certificate:

1. **SSL Context Creation**: A custom SSL context is created using Python's `ssl.create_default_context()`
2. **Certificate Loading**: The CA certificate is loaded using `ctx.load_verify_locations(cadata=ca_certificate)`
3. **Signature Validation** (if enabled): The certificate signature is validated using Ed25519 to ensure it hasn't been tampered with
4. **HTTPS Client Configuration**: The SSL context is passed to the HTTPX client as the `verify` parameter
5. **Secure Connection**: All HTTPS requests to the MCP server use the custom CA certificate for validation

### Usage During Gateway Registration

When registering or federating with a gateway:

1. The custom CA certificate is retrieved from the database
2. An SSL context is created with the certificate
3. The gateway initializes the connection using the custom SSL context
4. Tools, resources, and prompts are discovered over the secure connection

### Code Implementation Details

The implementation includes:

-   **Frontend validation** (`admin.js`): Client-side certificate validation with detailed feedback
-   **Backend storage** (`gateway_service.py`): SSL context creation and certificate management
-   **Tool invocation** (`tool_service.py`): Custom HTTPX client factory with CA certificate support
-   **Database schema** (`db.py`): Secure storage with optional cryptographic signing

## Common Use Cases

### Development Environments

Use custom CA certificates when:

-   Testing with locally hosted MCP servers using self-signed certificates
-   Connecting to development environments with internal certificate authorities
-   Working with staging servers that use non-public CAs

### Internal Networks

Ideal for:

-   Enterprise environments with internal PKI infrastructure
-   Private cloud deployments with custom certificate authorities
-   Air-gapped networks with self-signed certificates

### Certificate Chain Management

Handle complex scenarios:

-   Upload root CA and intermediate certificates separately
-   Automatic ordering ensures proper certificate chain validation
-   Support for multiple certificate authorities

## Security Considerations

### Certificate Integrity

-   **Ed25519 Signing** (optional): When enabled, certificates are cryptographically signed to prevent tampering
-   **Signature Validation**: Certificates are validated before use to ensure they haven't been modified
-   **Database Security**: Certificates are stored securely in the database with appropriate access controls

### Best Practices

1. **Use Strong CAs**: Only upload certificates from trusted certificate authorities, even for self-signed scenarios
2. **Rotate Regularly**: Update certificates before they expire
3. **Limit Access**: Restrict CA certificate upload permissions to administrators only
4. **Audit Trail**: All certificate uploads are tracked with metadata (created_by, created_at, modified_by, etc.)
5. **Verify Origins**: Only accept certificate files from trusted sources

### What NOT to Do

-   ❌ Don't upload expired certificates
-   ❌ Don't share certificate files insecurely
-   ❌ Don't use the same CA certificate for production and development
-   ❌ Don't upload private keys (only CA certificates should be uploaded)

## Troubleshooting

### Certificate Upload Fails

**Problem**: "Invalid file type" error

-   **Solution**: Ensure your file has extension `.pem`, `.crt`, `.cer`, or `.cert`

**Problem**: "Certificate file too large" error

-   **Solution**: Certificate files should be under 10 MB. If you have a large chain, split it into separate files.

**Problem**: "Some certificates failed validation"

-   **Solution**: Check that the file is a valid PEM-encoded X.509 certificate. Open it in a text editor and verify it contains `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----` markers with valid base64 content between them.

### Connection Still Fails After Upload

**Problem**: HTTPS connection fails even with CA certificate uploaded

1. **Verify the certificate**: Ensure you uploaded the correct root CA certificate that signed the server's certificate
2. **Check the URL**: Confirm the gateway URL matches the certificate's Common Name (CN) or Subject Alternative Name (SAN)
3. **Test the certificate**: Use `openssl s_client -connect <server>:<port> -CAfile <cert_file>` to verify the certificate works
4. **Check logs**: Review gateway logs for SSL/TLS errors that provide more details

### Certificate Chain Issues

**Problem**: "Certificate verification failed" errors

-   **Solution**: If you have intermediate CAs, make sure to upload the complete chain (root + intermediates)
-   **Order matters**: Upload all certificates, and the system will automatically order them correctly

## Example: Creating and Using a Self-Signed Certificate

For testing purposes, here's how to create a self-signed certificate and use it with ContextForge:

### 1. Generate a Self-Signed Certificate

```bash
# Generate private key and certificate
openssl req -x509 -newkey rsa:4096 -keyout server-key.pem -out server-cert.pem -days 365 -nodes \
  -subj "/CN=mcp-server.local/O=MyOrg/C=US"

# Extract the CA certificate (for self-signed, it's the same as the server cert)
cp server-cert.pem ca-cert.pem
```

### 2. Start Your MCP Server with the Certificate

```bash
# Use the certificate with your MCP server
./mcp-server --cert server-cert.pem --key server-key.pem --port 8443
```

### 3. Upload to ContextForge

1. In ContextForge admin panel, go to **Gateways** → **Add Gateway**
2. Enter the server URL: `https://mcp-server.local:8443`
3. Upload the `ca-cert.pem` file in the CA Certificate section
4. Save the gateway configuration

### 4. Verify the Connection

The gateway will now successfully connect to your self-signed MCP server and discover its tools, resources, and prompts.

## API Reference

For programmatic certificate management, see the API documentation:

-   `POST /admin/gateways` - Create gateway with CA certificate
-   `PUT /admin/gateways/{id}` - Update gateway CA certificate
-   Certificate field: `ca_certificate` (PEM-encoded string or file upload)

## Related Documentation

-   [Gateway Management](api-usage.md#gateway-management)
-   [Security Configuration](securing.md)
-   [TLS/SSL Setup](../deployment/tls-configuration.md)
