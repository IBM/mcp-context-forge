# Multi-stage container for {{ cookiecutter.project_name }}

# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.

FROM golang:{{ cookiecutter.go_version }} AS builder
WORKDIR /src

COPY go.mod .
RUN go mod download
COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/{{ cookiecutter.bin_name }} .

FROM scratch
LABEL org.opencontainers.image.source=https://github.com/contextforge/mcp-context-forge

COPY --from=builder /usr/local/bin/{{ cookiecutter.bin_name }} /{{ cookiecutter.bin_name }}

USER 1001:1001
ENTRYPOINT ["/{{ cookiecutter.bin_name }}"]
