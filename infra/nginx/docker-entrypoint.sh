#!/bin/sh
# Nginx TLS Entrypoint Script
# Handles optional HTTP->HTTPS redirect based on environment variable

set -e

NGINX_CONF="/etc/nginx/nginx.conf"
NGINX_CONF_ORIG="/etc/nginx/nginx.conf.orig"

# If NGINX_FORCE_HTTPS is set to "true", enable the redirect block
if [ "$NGINX_FORCE_HTTPS" = "true" ]; then
    echo "🔒 NGINX_FORCE_HTTPS=true: Enabling HTTP -> HTTPS redirect"

    # Check if we're using the TLS config (has the commented redirect block)
    if grep -q "# Uncomment this block to force HTTP -> HTTPS redirect" "$NGINX_CONF"; then
        # Copy config to a writable location (in case it's mounted read-only)
        cp "$NGINX_CONF" /tmp/nginx.conf

        # Uncomment the redirect server block
        sed -i '
            /# Uncomment this block to force HTTP -> HTTPS redirect/,/# HTTP server block/ {
                s/^[[:space:]]*# server {/    server {/
                s/^[[:space:]]*#[[:space:]]*listen 80;/        listen 80;/
                s/^[[:space:]]*#[[:space:]]*listen \[::\]:80;/        listen [::]:80;/
                s/^[[:space:]]*#[[:space:]]*server_name localhost;/        server_name localhost;/
                s/^[[:space:]]*#[[:space:]]*return 301/        return 301/
                s/^[[:space:]]*# }/    }/
            }
        ' /tmp/nginx.conf

        # Comment out the regular HTTP server block listeners to avoid port conflict
        sed -i '
            /# HTTP server block (keeps HTTP available alongside HTTPS)/,/^[[:space:]]*server_name localhost;/ {
                s/^\([[:space:]]*\)listen 80 backlog/\1# listen 80 backlog/
                s/^\([[:space:]]*\)listen \[::\]:80 backlog/\1# listen [::]:80 backlog/
            }
        ' /tmp/nginx.conf

        # Use the modified config
        cp /tmp/nginx.conf "$NGINX_CONF" 2>/dev/null || {
            # If we can't write to /etc/nginx, use -c flag to specify config path
            NGINX_CONF="/tmp/nginx.conf"
        }

        echo "✅ HTTP -> HTTPS redirect enabled (all HTTP requests redirect to HTTPS)"
    else
        echo "⚠️  NGINX_FORCE_HTTPS set but redirect block not found in config"
    fi
else
    echo "ℹ️  NGINX_FORCE_HTTPS not set: Both HTTP and HTTPS available"
fi

# Validate nginx configuration
echo "🔍 Validating nginx configuration..."
nginx -t -c "$NGINX_CONF"

# Start nginx
echo "🚀 Starting nginx..."
exec nginx -c "$NGINX_CONF" -g "daemon off;"
