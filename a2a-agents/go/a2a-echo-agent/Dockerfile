# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
# Using Red Hat UBI 9 Go Toolset for enterprise-grade security and IBM alignment
FROM registry.access.redhat.com/ubi9/go-toolset:1.26 AS builder
USER root
RUN dnf install -y git tzdata ca-certificates && dnf clean all
ENV GOTOOLCHAIN=go1.26.4
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/a2a-echo-agent .

# Static binary (CGO_ENABLED=0) from builder stage contains everything needed.

FROM scratch

# Copy CA certificates for HTTPS calls
COPY --from=builder /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/certs/ca-certificates.crt

# Copy timezone data for time.LoadLocation()
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# Copy binary
COPY --from=builder /usr/local/bin/a2a-echo-agent /a2a-echo-agent

USER 1001:1001
EXPOSE 9100
ENTRYPOINT ["/a2a-echo-agent"]
