# Multi-stage container for {{ cookiecutter.project_name }}

# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
# Using Red Hat UBI 9 Go Toolset for enterprise-grade security and IBM alignment

FROM registry.access.redhat.com/ubi9/go-toolset:{{ cookiecutter.go_version }} AS builder
USER root
RUN dnf install -y git tzdata ca-certificates && dnf clean all
ENV GOTOOLCHAIN=go1.26.3
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download
COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/{{ cookiecutter.bin_name }} .

FROM scratch
LABEL org.opencontainers.image.source=https://github.com/contextforge/mcp-context-forge

# Copy CA certificates for HTTPS calls
COPY --from=builder /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

# Copy timezone data for time.LoadLocation()
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# Copy binary
COPY --from=builder /usr/local/bin/{{ cookiecutter.bin_name }} /{{ cookiecutter.bin_name }}

USER 1001:1001
ENTRYPOINT ["/{{ cookiecutter.bin_name }}"]
