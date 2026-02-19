# =============================================================================
# SLOW-TIME-SERVER - Multi-stage Containerfile
# =============================================================================
#
# Default runtime = DUAL transport  ->  SSE  (/sse, /messages)
#                                   ->  HTTP (/http) on port 8081
#
# Build:  docker build -t slow-time-server:latest --build-arg VERSION=$(git rev-parse --short HEAD) .
# Run :  docker run --rm -p 8081:8081 slow-time-server:latest
# Run :  docker run --rm -p 8081:8081 -e DEFAULT_LATENCY=30s slow-time-server:latest
# =============================================================================

# =============================================================================
# STAGE 1 - BUILD STATIC BINARY (Go 1.23, CGO disabled)
# =============================================================================
FROM golang:1.23 AS builder

ARG TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .

ARG VERSION=dev

RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH} go build \
      -trimpath \
      -ldflags "-s -w -X 'main.appVersion=${VERSION}'" \
      -o /usr/local/bin/slow-time-server .

# =============================================================================
# STAGE 2 - MINIMAL RUNTIME (scratch + tzdata + binary)
# =============================================================================
FROM scratch
LABEL org.opencontainers.image.source=https://github.com/IBM/mcp-context-forge

# copy tzdata so time.LoadLocation works
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# copy binary
COPY --from=builder /usr/local/bin/slow-time-server /slow-time-server

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["/slow-time-server", "-health", "-port=8081"]

USER 1001:1001
ENTRYPOINT ["/slow-time-server"]
CMD ["-transport=dual", "-port=8081", "-listen=0.0.0.0"]
