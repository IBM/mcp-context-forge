# High-Performance Nginx Caching Proxy for MCP Gateway
# Based on Red Hat UBI 10.1 Minimal for consistency with gateway container

FROM registry.access.redhat.com/ubi10/ubi-minimal:10.1-1764604111

# Install nginx and curl (for healthchecks)
RUN microdnf install -y \
        nginx \
        curl-minimal \
        ca-certificates \
    && microdnf clean all \
    && rm -rf /var/cache/yum

# Create cache directories with proper permissions
RUN mkdir -p /var/cache/nginx/static \
             /var/cache/nginx/api \
             /var/cache/nginx/schema \
             /var/log/nginx \
             /run/nginx && \
    chown -R nginx:nginx /var/cache/nginx /var/log/nginx /run/nginx && \
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
