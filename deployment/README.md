# Deployment scripts

This directory will host charts, k8s, ansible and terraform scripts.

The charts will be published here:

https://github.com/orgs/IBM/packages/container/package/mcp-context-forge%2Fmcp-stack

## Container Build Process

### Tailwind CSS Build

The container build process includes a Node.js build stage that compiles Tailwind CSS from source. This ensures the application works without requiring the Tailwind CDN and removes the need for `unsafe-eval` in the Content Security Policy.

**Build stages:**

1. **Node.js builder** - Compiles `mcpgateway/static/css/tailwind.src.css` → `tailwind.min.css`
2. **Rust builder** (optional) - Builds Rust plugins if `ENABLE_RUST=true`
3. **Main application** - Copies pre-built CSS and runs the Python application

**Required files for CSS build:**

- `package.json` - Node.js dependencies (tailwindcss, postcss, autoprefixer)
- `package-lock.json` - Locked dependency versions
- `tailwind.config.js` - Tailwind configuration with content paths
- `postcss.config.js` - PostCSS configuration
- `mcpgateway/static/css/tailwind.src.css` - Source CSS file
- `mcpgateway/templates/**/*.html` - Templates for content scanning
- `mcpgateway/static/**/*.js` - JavaScript files for content scanning

**Build command:**

```bash
# Standard build (without Rust plugins)
docker build -t mcpgateway:latest .

# Build with Rust plugins
docker build --build-arg ENABLE_RUST=true -t mcpgateway:latest .
```

**Verification:**
After building, verify the CSS file exists in the container:

```bash
docker run --rm mcpgateway:latest ls -lh /app/mcpgateway/static/css/tailwind.min.css
```

### CI/CD Integration

When deploying via CI/CD pipelines, ensure:

1. Node.js 20+ is available in the build environment (handled by multi-stage build)
2. The `package.json` and related config files are not excluded by `.dockerignore`
3. The build process has sufficient memory (Tailwind compilation can be memory-intensive)

### Local Development

For local development without Docker:

```bash
# Install Node.js dependencies
npm install

# Build CSS once
make build-css

# Or watch for changes during development
make watch-css
```

The pre-built `tailwind.min.css` is excluded from git (`.gitignore`) but will be generated during:

- Local development: `make build-css` or `make watch-css`
- Container builds: Automatically via Node.js builder stage
