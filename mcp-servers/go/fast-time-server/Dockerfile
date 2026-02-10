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
# =============================================================================
FROM golang:1.23 AS builder

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

# copy tzdata so time.LoadLocation works
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# copy binary
COPY --from=builder /usr/local/bin/fast-time-server /fast-time-server

# --- default: SSE + HTTP on 8080 ---
USER 1001:1001
ENTRYPOINT ["/fast-time-server"]
CMD ["-transport=dual", "-port=8080", "-listen=0.0.0.0"]
