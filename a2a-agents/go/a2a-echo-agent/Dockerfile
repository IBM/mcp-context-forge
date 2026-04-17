# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
FROM golang:1.26.2 AS builder
ENV PATH=/usr/local/go/bin:$PATH
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/a2a-echo-agent .

# Use Debian slim so basic tooling exists without Alpine.
FROM debian:bookworm-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates tzdata wget && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --uid 1001 --create-home --shell /usr/sbin/nologin app
COPY --from=builder /usr/local/bin/a2a-echo-agent /usr/local/bin/a2a-echo-agent
USER 1001:1001
EXPOSE 9100
ENTRYPOINT ["/usr/local/bin/a2a-echo-agent"]
