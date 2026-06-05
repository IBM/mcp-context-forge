# =============================================================================
# 🦫 FAST-TIME-SERVER - Multi-stage Containerfile
# =============================================================================
#
# Default runtime = DUAL transport  →  SSE  (/sse, /messages)
#                                   →  HTTP (/http) on port 8080
#
# Build:  docker build -t fast-time-server:latest --build-arg VERSION=$(git rev-parse --short HEAD) .
# Run :  docker run --rm -p 8080:8080 fast-time-server:latest
#        # now visit http://localhost:8080/sse   or   http://localhost:8080/http
#
# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
# =============================================================================

# =============================================================================
# 🏗️  STAGE 1 - BUILD STATIC BINARY (Go 1.23, CGO disabled)
# Using Red Hat UBI 9 Go Toolset for enterprise-grade security and IBM alignment
# =============================================================================
FROM registry.access.redhat.com/ubi9/go-toolset:1.26 AS builder
USER root
RUN dnf install -y git tzdata ca-certificates && dnf clean all
ENV GOTOOLCHAIN=go1.26.3

# Accept target architecture from buildx for cross-compilation
ARG TARGETARCH

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .

ARG VERSION=dev

RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build \
      -trimpath \
      -ldflags "-s -w -X 'main.appVersion=${VERSION}'" \
      -o /usr/local/bin/fast-time-server .

# =============================================================================
# 📦  STAGE 2 - MINIMAL RUNTIME (scratch + tzdata + binary)
# =============================================================================
FROM scratch
LABEL org.opencontainers.image.source=https://github.com/IBM/mcp-context-forge

# Copy CA certificates for HTTPS calls
COPY --from=builder /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

# Copy tzdata so time.LoadLocation works
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# Copy binary
COPY --from=builder /usr/local/bin/fast-time-server /fast-time-server

# --- default: SSE + HTTP on 8080 ---
USER 1001:1001
ENTRYPOINT ["/fast-time-server"]
CMD ["-transport=dual", "-port=8080", "-listen=0.0.0.0"]
