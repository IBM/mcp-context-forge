# High-Performance Nginx Caching Proxy for MCP Gateway
# Based on Alpine Linux for minimal size and optimal performance

FROM nginx:1.27-alpine

# Install required tools for cache management
RUN apk add --no-cache \
    curl \
    ca-certificates

# Create cache directories with proper permissions
RUN mkdir -p /var/cache/nginx/static \
             /var/cache/nginx/api \
             /var/cache/nginx/schema && \
    chown -R nginx:nginx /var/cache/nginx && \
    chmod -R 755 /var/cache/nginx

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Note: nginx -t validation removed from build because it requires runtime
# DNS resolution of upstream servers (gateway:4444). Configuration is still
# validated when nginx starts at runtime via CMD below.

# Expose HTTP port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/health || exit 1

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
