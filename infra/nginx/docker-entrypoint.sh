#!/bin/sh
# Nginx TLS Entrypoint Script
# Handles optional HTTP->HTTPS redirect based on environment variable

set -e

NGINX_CONF_ORIG="/etc/nginx/nginx.conf"
NGINX_CONF="/tmp/nginx.conf"
cp "$NGINX_CONF_ORIG" "$NGINX_CONF"

GATEWAY_SCHEME="${GATEWAY_SCHEME:-http}"
case "$GATEWAY_SCHEME" in
    http|https) ;;
    *)
        echo "❌ GATEWAY_SCHEME must be http or https, got: $GATEWAY_SCHEME"
        exit 1
        ;;
esac

if grep -q "__GATEWAY_SCHEME__" "$NGINX_CONF"; then
    sed -i "s/__GATEWAY_SCHEME__/$GATEWAY_SCHEME/g" "$NGINX_CONF"
fi

# If NGINX_FORCE_HTTPS is set to "true", enable the redirect block
if [ "$NGINX_FORCE_HTTPS" = "true" ]; then
    echo "🔒 NGINX_FORCE_HTTPS=true: Enabling HTTP -> HTTPS redirect"

    # The active config is already a writable copy in /tmp.
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
    ' "$NGINX_CONF"

    # Comment out the regular HTTP server block listeners to avoid port conflict
    sed -i '
        /# HTTP server block (keeps HTTP available alongside HTTPS)/,/^[[:space:]]*server_name localhost;/ {
            s/^\([[:space:]]*\)listen 80 backlog/\1# listen 80 backlog/
            s/^\([[:space:]]*\)listen \[::\]:80 backlog/\1# listen [::]:80 backlog/
        }
    ' "$NGINX_CONF"

    echo "✅ HTTP -> HTTPS redirect enabled (all HTTP requests redirect to HTTPS)"
else
    echo "⚠️  NGINX_FORCE_HTTPS set but redirect block not found in config"
fi

# Validate nginx configuration
echo "🔍 Validating nginx configuration..."
nginx -t -c "$NGINX_CONF"

# Start nginx
echo "🚀 Starting nginx..."
exec nginx -c "$NGINX_CONF" -g "daemon off;"
