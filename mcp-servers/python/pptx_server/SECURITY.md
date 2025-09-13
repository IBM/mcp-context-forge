# PowerPoint MCP Server - Security & Configuration Guide

## 🔒 Security Features

The PowerPoint MCP Server includes comprehensive security features for safe file handling, session management, and access control.

## 📋 Environment Configuration

### Configuration Files
- `.env.example` - Template with all available settings
- `.env` - Local configuration (git-ignored)

### Quick Setup
```bash
# Copy and customize configuration
cp .env.example .env

# Edit configuration for your environment
nano .env

# Install with security dependencies
pip install -e ".[dev]"
```

## 🛡️ Security Architecture

### Secure Directory Structure
```
/tmp/pptx_server/                 # Configurable work directory
├── sessions/                     # UUID-based session isolation
│   └── {session-id}/
│       ├── session.json          # Session metadata
│       ├── uploads/              # Uploaded files
│       └── presentations/        # Session presentations
├── templates/                    # Global template storage
├── output/                       # Default presentation output
├── uploads/                      # Global uploads (if no session)
└── logs/                         # Server logs
```

### File Security
- **Path Validation**: All filenames sanitized and validated
- **Directory Isolation**: Operations restricted to configured directories
- **Permission Control**: Secure file permissions (0o600/0o700)
- **Extension Filtering**: Only allowed file types accepted
- **Size Limits**: Configurable file and presentation size limits

### Session Management
- **UUID Isolation**: Each session gets unique workspace
- **Temporary Storage**: Sessions auto-expire with cleanup
- **Resource Limits**: Max files and operations per session
- **Access Control**: Download tokens with expiration

## 🔧 Configuration Options

### Server Settings
```env
PPTX_SERVER_PORT=9000                    # Server port
PPTX_SERVER_HOST=localhost               # Bind address
PPTX_SERVER_DEBUG=false                  # Debug mode
```

### Directory Configuration
```env
PPTX_WORK_DIR=/tmp/pptx_server          # Main work directory
PPTX_TEMP_DIR=/tmp/pptx_server/temp     # Temporary files
PPTX_TEMPLATES_DIR=/tmp/pptx_server/templates  # Template storage
PPTX_OUTPUT_DIR=/tmp/pptx_server/output        # Default output
PPTX_UPLOADS_DIR=/tmp/pptx_server/uploads      # File uploads
```

### Security Settings
```env
PPTX_ENABLE_FILE_UPLOADS=true           # Allow file uploads
PPTX_MAX_FILE_SIZE_MB=50                # Max upload size
PPTX_MAX_PRESENTATION_SIZE_MB=100       # Max presentation size
PPTX_ALLOWED_UPLOAD_EXTENSIONS=png,jpg,jpeg,gif,bmp,pptx  # Allowed types
PPTX_ENABLE_DOWNLOADS=true              # Allow downloads
PPTX_DOWNLOAD_TOKEN_EXPIRY_HOURS=24     # Download link expiry
```

### File Management
```env
PPTX_AUTO_CLEANUP_HOURS=48              # Auto cleanup interval
PPTX_MAX_FILES_PER_SESSION=50           # Files per session limit
PPTX_ENABLE_FILE_VERSIONING=true        # File versioning
PPTX_DEFAULT_SLIDE_FORMAT=16:9          # Default aspect ratio
```

### Authentication (Optional)
```env
PPTX_REQUIRE_AUTH=false                 # Require authentication
PPTX_API_KEY=your-secret-key            # API key for auth
PPTX_JWT_SECRET=your-jwt-secret         # JWT signing secret
```

### Resource Limits
```env
PPTX_MAX_MEMORY_MB=512                  # Memory limit
PPTX_MAX_CONCURRENT_OPERATIONS=10       # Concurrent ops
PPTX_OPERATION_TIMEOUT_SECONDS=300      # Operation timeout
```

## 🛠️ Security Tools

### Session Management
```python
# Create secure session
session = await create_secure_session("My Presentation Session")
session_id = session["session_id"]
workspace = session["workspace_dir"]

# List session files
files = await list_session_files(session_id)
print(f"Session has {files['file_count']} files")

# Cleanup session
cleanup = await cleanup_session(session_id)
print(f"Removed {cleanup['files_removed']} files")
```

### File Upload System
```python
# Upload image for presentation
with open("logo.png", "rb") as f:
    file_data = base64.b64encode(f.read()).decode()

upload_result = await upload_file(
    file_data=file_data,
    filename="company_logo.png",
    session_id=session_id
)

# Use uploaded file in presentation
await add_image(
    "presentation.pptx",
    slide_index=0,
    image_path=upload_result["file_path"]
)
```

### Download Links
```python
# Create presentation
await create_presentation("report.pptx", "Quarterly Report")

# Generate secure download link
download = await create_download_link("report.pptx", session_id)
download_url = download["download_url"]  # /download/{token}
expires = download["expires"]            # ISO timestamp
```

### Server Status Monitoring
```python
status = await get_server_status()

print(f"Active sessions: {status['statistics']['active_sessions']}")
print(f"Total storage: {status['statistics']['total_storage_mb']} MB")
print(f"Security enabled: {status['security']['secure_directories']}")
```

## 🚨 Security Best Practices

### Production Deployment
```env
# Production security configuration
PPTX_WORK_DIR=/var/lib/pptx_server      # Dedicated directory
PPTX_REQUIRE_AUTH=true                  # Enable authentication
PPTX_API_KEY=generate-strong-key        # Strong API key
PPTX_MAX_FILE_SIZE_MB=25                # Stricter limits
PPTX_AUTO_CLEANUP_HOURS=24              # Frequent cleanup
PPTX_SERVER_HOST=127.0.0.1              # Local binding only
```

### File Handling Security
- **Validate all filenames** - No path traversal attacks
- **Restrict file types** - Only allowed extensions
- **Size limits** - Prevent resource exhaustion
- **Temporary storage** - Auto-cleanup expired files
- **Secure permissions** - Owner-only access (0o600/0o700)

### Session Security
- **UUID isolation** - Unique workspace per session
- **Time-based expiry** - Automatic cleanup
- **Resource limits** - Max files per session
- **Access tokens** - Secure download links

### Network Security
- **Local binding** - Default to localhost
- **Authentication** - Optional API key/JWT
- **Rate limiting** - Configurable request limits
- **Input validation** - All parameters validated

## 🔐 Authentication (Optional)

### API Key Authentication
```env
PPTX_REQUIRE_AUTH=true
PPTX_API_KEY=your-secure-api-key-here
```

### JWT Token Authentication
```env
PPTX_REQUIRE_AUTH=true
PPTX_JWT_SECRET=your-jwt-signing-secret
```

### Usage with Authentication
```python
# Include API key in requests
headers = {"X-API-Key": "your-api-key"}

# Or use JWT tokens
headers = {"Authorization": "Bearer your-jwt-token"}
```

## 📊 Monitoring & Logging

### Log Configuration
```env
PPTX_LOG_LEVEL=INFO                     # Log level
PPTX_LOG_TO_FILE=true                   # File logging
PPTX_LOG_FILE=/var/log/pptx_server.log  # Log file path
PPTX_LOG_ROTATION_SIZE_MB=10            # Log rotation size
```

### Monitoring Endpoints
```python
# Get server status and metrics
status = await get_server_status()

# Monitor resource usage
stats = status["statistics"]
config = status["configuration"]
security = status["security"]
```

## 🧹 Cleanup & Maintenance

### Automatic Cleanup
- **Session expiry**: Sessions automatically cleaned after configured hours
- **Download tokens**: Expired tokens automatically removed
- **Temporary files**: Auto-cleanup of old files
- **Resource limits**: Prevent unlimited file accumulation

### Manual Cleanup
```python
# Cleanup specific session
await cleanup_session(session_id, force=True)

# Server maintains cleanup automatically based on:
# - PPTX_AUTO_CLEANUP_HOURS
# - PPTX_DOWNLOAD_TOKEN_EXPIRY_HOURS
# - Session expiration timestamps
```

## ⚠️ Security Considerations

### File System Security
- All operations restricted to configured directories
- No access to system files outside work directory
- Filename sanitization prevents path traversal
- Secure file permissions prevent unauthorized access

### Resource Management
- File size limits prevent disk exhaustion
- Session limits prevent resource abuse
- Memory limits configured for stability
- Operation timeouts prevent hanging processes

### Network Security
- Default local binding (localhost)
- Optional authentication for access control
- Rate limiting to prevent abuse
- Input validation on all parameters

### Data Protection
- Temporary storage with automatic cleanup
- Session isolation prevents cross-contamination
- Download tokens expire automatically
- No persistent storage of sensitive data

## 🔄 Migration from Development

### Development → Production
```bash
# 1. Update configuration
cp .env.example .env.production
nano .env.production  # Configure for production

# 2. Set secure directories
mkdir -p /var/lib/pptx_server
chown pptx_user:pptx_group /var/lib/pptx_server
chmod 700 /var/lib/pptx_server

# 3. Enable authentication
PPTX_REQUIRE_AUTH=true
PPTX_API_KEY=$(openssl rand -hex 32)

# 4. Configure logging
PPTX_LOG_TO_FILE=true
PPTX_LOG_FILE=/var/log/pptx_server.log

# 5. Set resource limits
PPTX_MAX_FILE_SIZE_MB=25
PPTX_AUTO_CLEANUP_HOURS=24
```

## 📚 Integration Examples

### Secure Session Workflow
```python
# 1. Create secure session
session = await create_secure_session("Client Presentation Project")
session_id = session["session_id"]

# 2. Upload template/images
template_upload = await upload_file(template_data, "corporate_template.pptx", session_id)
logo_upload = await upload_file(logo_data, "company_logo.png", session_id)

# 3. Create presentation using uploaded files
await create_presentation_from_template(
    template_upload["file_path"],
    "client_presentation.pptx",
    replace_placeholders={"{{LOGO}}": logo_upload["file_path"]}
)

# 4. Generate download link
download = await create_download_link("client_presentation.pptx", session_id)
return download["download_url"]  # Share with client

# 5. Auto-cleanup after expiry (or manual cleanup)
```

### Enterprise Integration
```python
async def generate_department_reports():
    """Enterprise workflow with security."""

    # Create session for batch operation
    session = await create_secure_session("Monthly Department Reports")
    session_id = session["session_id"]

    try:
        # Upload corporate template
        template_upload = await upload_file(template_data, "dept_template.pptx", session_id)

        # Generate reports for each department
        departments = ["Sales", "Marketing", "Finance", "Operations"]
        download_links = {}

        for dept in departments:
            # Create department-specific presentation
            await create_presentation_from_template(
                template_upload["file_path"],
                f"{dept.lower()}_report.pptx",
                replace_placeholders={
                    "{{DEPARTMENT}}": dept,
                    "{{MONTH}}": "December 2024"
                }
            )

            # Generate download link
            download = await create_download_link(f"{dept.lower()}_report.pptx", session_id)
            download_links[dept] = download["download_url"]

        return download_links

    finally:
        # Optional: Cleanup session after use
        # await cleanup_session(session_id)
        pass  # Let auto-cleanup handle it
```

## 🛡️ Security Checklist

### Deployment Security
- [ ] Configure secure work directory (`/var/lib/pptx_server`)
- [ ] Set file permissions (700 for directories, 600 for files)
- [ ] Enable authentication for production use
- [ ] Configure resource limits appropriately
- [ ] Set up log rotation and monitoring
- [ ] Configure firewall rules (local access only)
- [ ] Regular security updates for dependencies

### Operational Security
- [ ] Monitor session usage and cleanup
- [ ] Review download token expiry settings
- [ ] Monitor file system usage
- [ ] Regular log review for suspicious activity
- [ ] Backup important templates securely
- [ ] Test disaster recovery procedures

## 📞 Security Support

For security issues or questions:
1. Review this security guide
2. Check server logs for security events
3. Monitor resource usage with `get_server_status`
4. Implement appropriate access controls for your environment

**Remember**: Security is a shared responsibility between the server configuration and your deployment environment.
