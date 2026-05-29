# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
# Using Red Hat UBI 9 Go Toolset for enterprise-grade security and IBM alignment
FROM registry.access.redhat.com/ubi9/go-toolset:1.26 AS builder
USER root
RUN dnf install -y git && dnf clean all
ENV GOTOOLCHAIN=auto
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/a2a-echo-agent .

# Use scratch for minimal attack surface
# Static binary (CGO_ENABLED=0) from builder stage contains everything needed.

FROM scratch
COPY --from=builder /usr/local/bin/a2a-echo-agent /a2a-echo-agent
USER 1001:1001
EXPOSE 9100
ENTRYPOINT ["/a2a-echo-agent"]
